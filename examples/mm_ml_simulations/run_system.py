"""
Create and run a mixed ML/MM system using openmm-ml.

TODO
Run a mixed openmm-ml hybrid system
Run a mixed openmm-ml hybrid system using customCVForce and scale the energies
"""

from openmm import app
import openmm
from openff.toolkit.topology import Molecule
from openmmforcefields.generators import SystemGenerator
# needed to triger the registering of the mace potential
from mace.calculators import openmm as mm
from openmmml import MLPotential
from openmmtools.openmm_torch import get_atoms_from_resname, RepexConstructor 
from openmm import unit


MACE_MODEL = "MACE_SPICE_larger.model"
SMALL_FF = "openff_unconstrained-1.0.0.offxml"
TOPOLOGY = "out-solvent.pdb"
LIGAND_TOPOLOGY = "ligand_12.sdf"
LIGAND_RSNAME = "MOL"

def main():

    ml_potential = MLPotential("mace", model_path=MACE_MODEL)
    pdbfile = app.PDBFile(TOPOLOGY)
    
    # make our MM system
    ff_kwargs = {'rigidWater' : True, 'removeCMMotion' : False}
    system_gen = SystemGenerator(forcefields=["amber/tip3p_standard.xml", "amber/tip3p_HFE_multivalent.xml"], small_molecule_forcefield=SMALL_FF, forcefield_kwargs=ff_kwargs)

    mm_system = system_gen.create_system(topology=pdbfile.topology, molecules=[Molecule.from_file(LIGAND_TOPOLOGY)])

    # extract the index of the atoms in the ligand
    ml_atoms = get_atoms_from_resname(pdbfile.topology, LIGAND_RSNAME)

    print("building ml mixed system ... ")
    ml_system = ml_potential.createMixedSystem(pdbfile.topology, mm_system, atoms=ml_atoms, interpolate=False)

    time_step = 0.5 * unit.femtoseconds  # simulation timestep
    friction = 1 / unit.picosecond  # collision rate
    temperature = 300 * unit.kelvin
    integrator = openmm.LangevinIntegrator(temperature, friction, time_step)

    ml_system.addForce(openmm.MonteCarloBarostat(1 * unit.atmosphere, temperature))
    print("Writing system to system.xml")
    with open("system.xml", "w") as output:
        output.write(openmm.XmlSerializer.serializeSystem(ml_system))

    simulation = openmm.app.Simulation(
        topology=pdbfile.topology,
        system=ml_system,
        integrator=integrator,
    )

    simulation.context.setPositions(pdbfile.positions)
    #  simulation.context.setVelocitiesToTemperature(temperature)
    dcd_reporter = openmm.app.DCDReporter("trajectory.dcd", 100, )
    state_data_reporter = openmm.app.StateDataReporter(
        "data.csv",
        100,
        step=True,
        potentialEnergy=True,
        volume=True,
        temperature=True,
        speed=True,
    )
    simulation.reporters.append(dcd_reporter)
    simulation.reporters.append(state_data_reporter)
    simulation.step(10_000)
    

if __name__ == "__main__":
    main()



