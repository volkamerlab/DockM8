import concurrent.futures
import math
import os
import shutil
import subprocess
import warnings
from pathlib import Path
from subprocess import DEVNULL, STDOUT

import pandas as pd
from chembl_structure_pipeline import standardizer
from rdkit import Chem
from rdkit.Chem import AllChem, PandasTools
from tqdm import tqdm

from scripts.utilities import parallel_executor, printlog, split_sdf_str

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

def standardize_molecule(molecule):
    standardized_molecule = standardizer.standardize_mol(molecule)
    standardized_molecule = standardizer.get_parent_mol(standardized_molecule)
    return standardized_molecule


# This function standardizes a docking library using the ChemBL Structure Pipeline.
def standardize_library(input_sdf: Path, output_dir: Path, id_column: str, ncpus: int):
    """
    Standardizes a docking library using the ChemBL Structure Pipeline.

    Args:
        input_sdf (Path): The path to the input SDF file containing the docking library.
        output_dir (Path): The directory where the standardized SDF file will be saved.
        id_column (str): The name of the column in the SDF file that contains the compound IDs.
        ncpus (int): The number of CPUs to use for parallel processing.

    Returns:
        None. The function writes the standardized molecules to a new SDF file.

    Raises:
        Exception: If there is an error loading the library SDF file.
        Exception: If there is an error converting SMILES to RDKit molecules.
        Exception: If there is an error writing the standardized library SDF file.
    """
    printlog('Standardizing docking library using ChemBL Structure Pipeline...')
    # Load Original Library SDF into Pandas
    try:
        df = PandasTools.LoadSDF(str(input_sdf),
                                idName=id_column,
                                molColName='Molecule',
                                includeFingerprints=False,
                                embedProps=True,
                                removeHs=True,
                                strictParsing=True,
                                smilesName='SMILES')
        df.rename(columns={id_column: 'ID'}, inplace=True)
        # Add 'DOCKM8-' in front of IDs that contain only numbers
        df['ID'] = ['DOCKM8-' + str(id) if str(id).isdigit() else id for id in df['ID']]
        # Replace underscore characters with hyphen in ID column
        df['ID'] = df['ID'].str.replace('_', '-')
        n_cpds_start = len(df)
    except BaseException:
        printlog('ERROR: Failed to Load library SDF file!')
        raise Exception('Failed to Load library SDF file!')
    try:
        # Convert SMILES to RDKit molecules
        df.drop(columns='Molecule', inplace=True)
        df['Molecule'] = [Chem.MolFromSmiles(smiles) for smiles in df['SMILES']]
    except Exception as e:
        printlog('ERROR: Failed to convert SMILES to RDKit molecules!' + e)
    # Standardize molecules using ChemBL Pipeline
    if ncpus == 1:
        # Standardize molecules sequentially
        df['Molecule'] = [standardizer.get_parent_mol(standardizer.standardize_mol(mol)) for mol in df['Molecule']]
    else:
        # Standardize molecules in parallel using multiple CPUs
        with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
            df['Molecule'] = list(tqdm(executor.map(standardize_molecule, df['Molecule']), total=len(df['Molecule']), desc='Standardizing molecules', unit='mol'))
    # Clean up the DataFrame
    df[['Molecule', 'flag']] = pd.DataFrame(df['Molecule'].tolist(), index=df.index)
    df = df.drop(columns='flag')
    df = df.loc[:, ~df.columns.duplicated()].copy()
    n_cpds_end = len(df)
    printlog(f'Standardization of compound library finished: Started with {n_cpds_start}, ended with {n_cpds_end}: {n_cpds_start-n_cpds_end} compounds lost')
    # Write standardized molecules to standardized SDF file
    output_sdf = output_dir / 'standardized_library.sdf'
    try:
        PandasTools.WriteSDF(df,
                            str(output_sdf),
                            molColName='Molecule',
                            idName='ID',
                            allNumeric=True)
    except BaseException:
        raise Exception('Failed to write standardized library SDF file!')

def conf_gen_RDKit(molecule):
    """
    Generates 3D conformers using RDKit.

    Args:
        molecule (RDKit molecule): The input molecule.

    Returns:
        molecule (RDKit molecule): The molecule with 3D conformers.
    """
    if not molecule.GetConformer().Is3D():
        molecule = Chem.AddHs(molecule)
        AllChem.EmbedMolecule(molecule)
        AllChem.MMFFOptimizeMolecule(molecule)
        AllChem.SanitizeMol(molecule)
    return molecule
def generate_conformers_RDKit(input_sdf: str, output_dir: str, ncpus: int):
    """
    Generates 3D conformers using RDKit.

    Args:
        input_sdf (str): Path to the input SDF file.
        output_dir (str): Path to the output directory.

    Returns:
        None
    """
    printlog('Generating 3D conformers using RDKit...')
    try:
        df = PandasTools.LoadSDF(str(input_sdf),
                                idName='ID',
                                molColName='Molecule',
                                includeFingerprints=False,
                                removeHs=False,
                                smilesName='SMILES')
        df = df.iloc[1:]  # Filter the dataframe to keep all rows except the first one
        with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
            df['Molecule'] = list(tqdm(executor.map(conf_gen_RDKit, df['Molecule']), total=len(df['Molecule']), desc='Minimizing molecules', unit='mol'))

        # Write the conformers to the output SDF file using PandasTools.WriteSDF()
        output_file = output_dir / 'gypsum_dl_success.sdf'
        PandasTools.WriteSDF(df, str(output_file), molColName='Molecule', idName='ID')
    except Exception as e:
        printlog('ERROR: Failed to generate conformers using RDKit!' + e)
    return


def generate_conformers_GypsumDL_withprotonation(input_sdf, output_dir, software, ncpus):
    """
    Generates protonation states and 3D conformers using GypsumDL.

    Args:
        input_sdf (str): Path to the input SDF file.
        output_dir (str): Path to the output directory.
        software (str): Path to the GypsumDL software.
        ncpus (int): Number of CPUs to use for the calculation.

    Raises:
        Exception: If failed to generate protomers and conformers.

    """
    printlog('Calculating protonation states and generating 3D conformers using GypsumDL...')
    printlog('Splitting input SDF file into smaller files for parallel processing...')
    n_splits = 10
    split_files_folder = split_sdf_str(output_dir / 'GypsumDL_split', input_sdf, n_splits)
    split_files_sdfs = [split_files_folder / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]

    global gypsum_dl_run
    def gypsum_dl_run(split_file, output_dir, cpus):
        results_dir = output_dir / 'GypsumDL_results'
        try:
            gypsum_dl_command = f'python {software}/gypsum_dl-1.2.1/run_gypsum_dl.py -s {split_file} -o {results_dir} --job_manager multiprocessing -p {cpus} -m 1 -t 10 --min_ph 6.5 --max_ph 7.5 --pka_precision 1 --skip_alternate_ring_conformations --skip_making_tautomers --skip_enumerate_chiral_mol --skip_enumerate_double_bonds --max_variants_per_compound 1 --separate_output_files'
            subprocess.call(
                gypsum_dl_command,
                shell=True,
                stdout=DEVNULL,
                stderr=STDOUT,
            )
        except Exception as e:
            printlog('ERROR: Failed to generate protomers and conformers!')
            printlog(e)
        return

    printlog('Running GypsumDL in parallel...')
    n_workers = 3
    parallel_executor(gypsum_dl_run,
                      split_files_sdfs,
                      n_workers,
                      output_dir=output_dir,
                      cpus=math.ceil(ncpus // n_workers))

    results_dfs = []

    for file in os.listdir(output_dir / 'GypsumDL_results'):
        if file.endswith('.sdf'):
            sdf_df = PandasTools.LoadSDF(str(output_dir / 'GypsumDL_results' /
                                             file),
                                         molColName='Molecule',
                                         idName='ID',
                                         removeHs=False)
            results_dfs.append(sdf_df)

    final_df = pd.concat(results_dfs)

    PandasTools.WriteSDF(final_df,
                         str(output_dir / 'gypsum_dl_success.sdf'),
                         molColName='Molecule',
                         idName='ID')
    shutil.rmtree(output_dir / 'GypsumDL_results')
    shutil.rmtree(output_dir / 'GypsumDL_split')


def GypsumDL_onlyprotonation(input_sdf, output_dir, software, ncpus):
    """
    Generates protonation states and 3D conformers using GypsumDL.

    Args:
        input_sdf (str): Path to the input SDF file.
        output_dir (str): Path to the output directory.
        software (str): Path to the GypsumDL software.
        ncpus (int): Number of CPUs to use for the calculation.

    Raises:
        Exception: If failed to generate protomers and conformers.

    """
    printlog('Calculating protonation states using GypsumDL...')
    try:
        gypsum_dl_command = f'python {software}/gypsum_dl-1.2.1/run_gypsum_dl.py -s {input_sdf} -o {output_dir} --job_manager multiprocessing -p {ncpus} -m 1 -t 10 --min_ph 6.5 --max_ph 7.5 --pka_precision 1 --skip_alternate_ring_conformations --skip_making_tautomers --skip_enumerate_chiral_mol --skip_enumerate_double_bonds --max_variants_per_compound 1 --2d_output_only'
        subprocess.call(
            gypsum_dl_command,
            shell=True,
            stdout=DEVNULL,
            stderr=STDOUT,
        )
    except Exception as e:
        printlog('ERROR: Failed to generate protomers!')
        printlog(e)


def generate_conformers_GypsumDL_noprotonation(input_sdf, output_dir, software,
                                               ncpus):
    """
    Generates 3D conformers using GypsumDL.

    Args:
        input_sdf (str): Path to the input SDF file.
        output_dir (str): Path to the output directory.
        software (str): Path to the GypsumDL software.
        ncpus (int): Number of CPUs to use for multiprocessing.

    Returns:
        None
    """
    printlog('Generating 3D conformers using GypsumDL...')
    try:
        gypsum_dl_command = f'python {software}/gypsum_dl-1.2.1/run_gypsum_dl.py -s {input_sdf} -o {output_dir} --job_manager multiprocessing -p {ncpus} -m 1 -t 10 --skip_adding_hydrogen --skip_alternate_ring_conformations --skip_making_tautomers --skip_enumerate_chiral_mol --skip_enumerate_double_bonds --max_variants_per_compound 1'
        subprocess.call(
            gypsum_dl_command,
            shell=True,
            stdout=DEVNULL,
            stderr=STDOUT,
        )
    except Exception as e:
        printlog('ERROR: Failed to generate conformers!')
        printlog(e)

def cleanup(input_sdf: str, output_dir: Path) -> pd.DataFrame:
    """
    Cleans up the temporary files generated during the library preparation process.

    Args:
        input_sdf (str): The path to the input SDF file containing the compound library.

    Returns:
        pd.DataFrame: The final DataFrame containing the cleaned-up library with only the 'Molecule' and 'ID' columns.
    """
    printlog('Cleaning up files...')

    # Load the successfully generated conformers from the GypsumDL process into a pandas DataFrame
    gypsum_df = PandasTools.LoadSDF(str(output_dir / 'gypsum_dl_success.sdf'), molColName='Molecule',idName='ID', removeHs=False)

    # Sanitize all the molecules in the DataFrame
    #for mol in gypsum_df['Molecule']:
    #    AllChem.SanitizeMol(mol)

    # END: abpxx6d04wxr

    # Remove the first row of the DataFrame, which contains the original input molecule
    final_df = gypsum_df.iloc[1:, :]

    # Select only the 'Molecule' and 'ID' columns from the DataFrame
    final_df = final_df[['Molecule', 'ID']]

    # Get the number of compounds in the final DataFrame
    n_cpds_end = len(final_df)

    # Write the final DataFrame to a new SDF file
    PandasTools.WriteSDF(final_df, str(output_dir / 'final_library.sdf'), molColName='Molecule', idName='ID')

    # Delete the temporary files generated during the library preparation process
    (output_dir / 'gypsum_dl_success.sdf').unlink(missing_ok=True)
    (output_dir / 'standardized_library.sdf').unlink(missing_ok=True)
    (output_dir / 'gypsum_dl_failed.smi').unlink(missing_ok=True)

    printlog(f'Preparation of compound library finished: ended with {n_cpds_end} compounds')

    return


def prepare_library(input_sdf: str, output_dir: Path, id_column: str, conformers: str, protonation: str, software: Path, ncpus: int):
    """
    Prepares a docking library for further analysis.
    
    Args:
        input_sdf (str): The path to the input SDF file containing the docking library.
        id_column (str): The name of the column in the SDF file that contains the compound IDs.
        protonation (str): The method to use for protonation. Can be 'GypsumDL', or 'None' for no protonation.
        ncpus (int): The number of CPUs to use for parallelization.
    """
    standardized_sdf = output_dir / 'standardized_library.sdf'

    if not standardized_sdf.is_file():
        standardize_library(input_sdf, output_dir, id_column, ncpus)

    if conformers == 'RDKit' or conformers == 'MMFF':
        if protonation == 'GypsumDL':
            GypsumDL_onlyprotonation(standardized_sdf, output_dir, software, ncpus)
            generate_conformers_RDKit(str(output_dir / 'gypsum_dl_success.sdf'), output_dir, ncpus)
        elif protonation == 'None':
            generate_conformers_RDKit(standardized_sdf, output_dir, ncpus)
        else:
            raise ValueError(f'Invalid protonation method specified : {protonation}. Must be either "None" or "GypsumDL".')
    elif conformers == 'GypsumDL':
        if protonation == 'GypsumDL':
            generate_conformers_GypsumDL_withprotonation(standardized_sdf, output_dir, software, ncpus)
        elif protonation == 'None':
            generate_conformers_GypsumDL_noprotonation(standardized_sdf, output_dir, software, ncpus)
        else:
            raise ValueError(f'Invalid protonation method specified : {protonation}. Must be either "None" or "GypsumDL".')
    else:
        raise ValueError(f'Invalid conformer method specified : {conformers}. Must be either "RDKit", "MMFF" or "GypsumDL".')

    cleanup(input_sdf, output_dir)
    return
