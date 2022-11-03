from qcelemental.models import AtomicResult, Provenance
from qcelemental.util import which_import, safe_version

from qcengine.programs.model import ProgramHarness
from qcengine.units import ureg
from typing import Dict, TYPE_CHECKING, Union
from qcengine.exceptions import InputError

if TYPE_CHECKING:
    from qcelemental.models import AtomicInput, FailedOperation

    from qcengine.config import TaskConfig





class MACEHarness(ProgramHarness):

    _CACHE = {}

    _defaults = {
        "name": "MACE",
        "scratch": False,
        "thread_safe": True,
        "thread_parallel": False,
        "node_parallel": False,
        "managed_memory": False,
    }
    version_cache: Dict[str, str] = {}

    def found(self, raise_error: bool = False) -> bool:
        return which_import(
            "mace",
            return_bool=True,
            raise_error=raise_error,
            raise_msg="Please install via github"
                             )

    def get_version(self) -> str:
        self.found(raise_error=True)

        which_prog = which_import("mace")
        if which_prog not in self.version_cache:
            import mace

            self.version_cache[which_prog] = safe_version(mace.__version__)

        return self.version_cache[which_prog]

    def load_model(self, name: str):
        """Compile and cahche the model to make it faster when calling many times in serial"""
        model_name = name.lower()
        if model_name in self._CACHE:
            return self._CACHE[model_name]

        import torch
        from e3nn.util import jit
        model = torch.load(name)
        comp_mod = jit.compile(model)
        self._CACHE[model_name] = (comp_mod, model.r_max, model.atomic_numbers)
        return self._CACHE[model_name]

    def compute(self, input_data: "AtomicInput", config: "TaskConfig") -> Union["AtomicResult", "FailedOperation"]:

        self.found(raise_error=True)

        import torch
        from mace.data.utils import Configuration, AtomicNumberTable
        import numpy as np
        from mace.tools.torch_geometric import DataLoader
        from mace.data import AtomicData
        import mace

        torch.set_default_dtype(torch.float64)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # Failure flag
        ret_data = {"success": False}

        # Build model
        method = input_data.model.method

        # load the torch model assuming the file is local
        model, r_max, atomic_numbers = self.load_model(name=method)

        z_table = AtomicNumberTable([int(z) for z in atomic_numbers])
        atomic_numbers = input_data.molecule.atomic_numbers
        pbc = (False, False, False)
        # create some large cell
        cell = np.array([[50.0, 0.0, 0.0], [0.0, 50.0, 0.0], [0.0, 0.0, 50.0]])

        config = Configuration(
            atomic_numbers=atomic_numbers,
            positions=input_data.molecule.geometry * ureg.conversion_factor("bohr", "angstrom"),
            pbc=pbc,
            cell=cell,
            weight=1
        )

        data_loader = DataLoader(dataset=[AtomicData.from_config(config, z_table=z_table, cutoff=r_max)],
                                 batch_size=1,
                                 shuffle=False,
                                 drop_last=False,
                                 )
        input_dict = next(iter(data_loader)).to_dict()
        model.to(device)
        mace_data = model(input_dict, compute_force=True)
        ret_data["properties"] = {"return_energy": mace_data["energy"] * ureg.conversion_factor("eV", "hartree")}

        if input_data.driver == "energy":
            ret_data["return_result"] = ret_data["properties"]["return_energy"]
        elif input_data.driver == "gradient":
            ret_data["return_result"] = np.asarray(-1.0 * mace_data["forces"] * ureg.conversion_factor("eV / angstrom", "hartree / bohr") / ureg.conversion_factor("angstrom", "bohr")).ravel().tolist()

        else:
            raise InputError("MACE only supports the energy and gradient driver methods.")

        ret_data["extras"] = input_data.extras.copy()
        ret_data["provenance"] = Provenance(
            creator="mace", version=mace.__version__, routine="mace"
        )
        ret_data["schema_name"] = "qcschema_output"
        ret_data["success"] = True

        # Form up a dict first, then sent to BaseModel to avoid repeat kwargs which don't override each other
        return AtomicResult(**{**input_data.dict(), **ret_data})