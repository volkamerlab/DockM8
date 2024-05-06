import concurrent.futures
import sys
import warnings
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, PandasTools
from tqdm import tqdm

# Search for 'DockM8' in parent directories
dockm8_path = next((p / 'DockM8' for p in Path(__file__).resolve().parents if (p / 'DockM8').is_dir()), None)
sys.path.append(str(dockm8_path))

from scripts.utilities.utilities import printlog

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

def conf_gen_RDKit(molecule):
    """
    Generates 3D conformers using RDKit.

    Args:
        molecule (RDKit molecule): The input molecule.

    Returns:
        molecule (RDKit molecule): The molecule with 3D conformers.
    """
    if not molecule.GetConformer().Is3D():
        molecule = Chem.AddHs(molecule)  # Add hydrogens to the molecule
        AllChem.EmbedMolecule(molecule)  # Generate initial 3D coordinates for the molecule
        AllChem.MMFFOptimizeMolecule(molecule)  # Optimize the 3D coordinates using the MMFF force field
        AllChem.SanitizeMol(molecule)  # Sanitize the molecule to ensure it is chemically valid
    return molecule

def generate_conformers_RDKit(input_sdf: str, output_dir: str, ncpus: int) -> Path:
    """
    Generates 3D conformers using RDKit.

    Args:
        input_sdf (str): Path to the input SDF file.
        output_dir (str): Path to the output directory.
        ncpus (int): Number of CPUs to use for parallel processing.

    Returns:
        output_file (Path): Path to the output SDF file containing the generated conformers.
    """
    printlog('Generating 3D conformers using RDKit...')

    try:
        # Load the input SDF file into a Pandas DataFrame
        df = PandasTools.LoadSDF(str(input_sdf),
                                idName='ID',
                                molColName='Molecule',
                                includeFingerprints=False,
                                removeHs=False,
                                smilesName='SMILES')
        # Generate conformers for each molecule in parallel using the conf_gen_RDKit function
        with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
            df['Molecule'] = list(tqdm(executor.map(conf_gen_RDKit, df['Molecule']), total=len(df['Molecule']), desc='Minimizing molecules', unit='mol'))

        # Write the conformers to the output SDF file using PandasTools.WriteSDF()
        output_file = output_dir / 'generated_conformers.sdf'
        PandasTools.WriteSDF(df, str(output_file), molColName='Molecule', idName='ID')
    except Exception as e:
        printlog('ERROR: Failed to generate conformers using RDKit!' + e)

    return output_file