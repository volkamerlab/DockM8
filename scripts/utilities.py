import os
import math

def create_temp_folder(path, silent=False):
    if os.path.isdir(path) == True:
        if silent == False:
            print(f'The folder: {path} already exists')
    else:
        os.mkdir(path)
        if silent == False:
            print(f'The folder: {path} was created')
        
from rdkit.Chem import PandasTools
from tqdm import tqdm
import math
        
def split_sdf(dir, sdf_file, ncpus):
    sdf_file_name = os.path.basename(sdf_file).replace('.sdf', '')
    print(f'Splitting SDF file {sdf_file_name}.sdf ...')
    split_files_folder = dir+f'/split_{sdf_file_name}'
    create_temp_folder(dir+f'/split_{sdf_file_name}', silent=True)
    for file in os.listdir(dir+f'/split_{sdf_file_name}'):
        os.unlink(os.path.join(dir+f'/split_{sdf_file_name}', file))
    df = PandasTools.LoadSDF(sdf_file, molColName='Molecule', idName='ID', includeFingerprints=False, strictParsing=True)
    compounds_per_core = math.ceil(len(df['ID'])/(ncpus*2))
    used_ids = set() # keep track of used 'ID' values
    file_counter = 1
    for i in tqdm(range(0, len(df), compounds_per_core), desc='Splitting files'):
        chunk = df[i:i+compounds_per_core]
        # remove rows with 'ID' values that have already been used
        chunk = chunk[~chunk['ID'].isin(used_ids)]
        used_ids.update(set(chunk['ID'])) # add new 'ID' values to used_ids
        PandasTools.WriteSDF(chunk, dir+f'/split_{sdf_file_name}/split_' + str(file_counter) + '.sdf', molColName='Molecule', idName='ID')
        file_counter+=1
    print(f'Split docking library into {file_counter-1} files each containing {compounds_per_core} compounds')
    return split_files_folder


def split_sdf_single(dir, sdf_file):
    sdf_file_name = os.path.basename(sdf_file).replace('.sdf', '')
    print(f'Splitting SDF file {sdf_file_name}.sdf ...')
    split_files_folder = dir+f'/split_{sdf_file_name}'
    create_temp_folder(dir+f'/split_{sdf_file_name}', silent=True)
    for file in os.listdir(dir+f'/split_{sdf_file_name}'):
        os.unlink(os.path.join(dir+f'/split_{sdf_file_name}', file))
    df = PandasTools.LoadSDF(sdf_file, molColName='Molecule', idName='ID', includeFingerprints=False, strictParsing=True)
    compounds_per_core = 1
    file_counter = 1
    for i in tqdm(range(0, len(df)), desc='Splitting files'):
        chunk = df.iloc[i:i+compounds_per_core]
        PandasTools.WriteSDF(chunk, dir+f'/split_{sdf_file_name}/split_' + str(file_counter) + '.sdf', molColName='Molecule', idName='ID')
        file_counter+=1
    print(f'Split SDF file into {file_counter-1} files each containing 1 compound')
    return split_files_folder

import pandas as pd

def Insert_row(row_number, df, row_value):
    start_index = 0
    last_index = row_number
    start_lower = row_number
    last_lower = df.shape[0]
    # Create a list of upper_half index and lower half index
    upper_half = [*range(start_index, last_index, 1)]
    lower_half = [*range(start_lower, last_lower, 1)]
    # Increment the value of lower half by 1
    lower_half = [x.__add__(1) for x in lower_half]  
    # Combine the two lists
    index_ = upper_half + lower_half
    # Update the index of the dataframe
    df.index = index_
    # Insert a row at the end
    df.loc[row_number] = row_value      
    # Sort the index labels
    df = df.sort_index()
    return df

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np

def show_correlation(input, annotation = bool()):
    if isinstance(input, pd.DataFrame):
        dataframe = input
    elif input.endswith('.sdf'):
        dataframe = PandasTools.LoadSDF(input)
    elif input.endswith('.csv'):
        dataframe = pd.read_csv(input, index_col=0)
    matrix = dataframe.corr().round(2)
    mask = np.triu(np.ones_like(matrix, dtype=bool))
    fig, ax = plt.subplots(figsize=(10,10))  
    sns.heatmap(matrix, mask = mask, annot=annotation, vmax=1, vmin=-1, center=0, linewidths=.5, cmap='coolwarm', ax=ax)
    plt.show()

import datetime

def printlog(message):
    def timestamp_generator():
        dateTimeObj = datetime.datetime.now()
        return "["+dateTimeObj.strftime("%Y-%b-%d %H:%M:%S")+"]"
    timestamp = timestamp_generator()
    msg = "\n" + \
        str(timestamp) + \
        ": "+str(message)
    print(msg)
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../log.txt')
    with open(log_file_path, 'a') as f_out:
        f_out.write(msg)

import openbabel
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

def parallel_sdf_to_pdbqt(input_file, output_dir, ncpus):
    def convert_molecule(mol, output_dir):
        obConversion = openbabel.OBConversion()
        obConversion.SetInAndOutFormats("sdf", "pdbqt")
        # Calculate Gasteiger charges
        charge_model = openbabel.OBChargeModel.FindType("gasteiger")
        charge_model.ComputeCharges(mol)
        mol_name = mol.GetTitle()

        if not mol_name:
            mol_name = f"molecule_{mol.GetIdx()}"

        valid_filename = "".join(c for c in mol_name if c.isalnum() or c in (' ','.','_')).rstrip()
        output_file = os.path.join(output_dir, f"{valid_filename}.pdbqt")
        obConversion.WriteFile(mol, output_file)

    obConversion = openbabel.OBConversion()
    obConversion.SetInAndOutFormats("sdf", "sdf")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    mol = openbabel.OBMol()
    not_at_end = obConversion.ReadFile(mol, input_file)
    molecules = []

    while not_at_end:
        molecules.append(openbabel.OBMol(mol))
        not_at_end = obConversion.Read(mol)

    try:
        with ThreadPoolExecutor(max_workers=ncpus) as executor:
            tasks = [executor.submit(convert_molecule, m, output_dir) for m in molecules]
            _ = [t.result() for t in tasks]
    except Exception as e:
        print(f"ERROR: Could note convert SDF file to .pdbqt: {e}")
    return len(molecules)

from meeko import MoleculePreparation

def meeko_to_pdbqt(sdf_path, output_dir):
    for mol in Chem.SDMolSupplier(sdf_path, removeHs=False):
        preparator = MoleculePreparation(min_ring_size=10)
        mol = Chem.AddHs(mol)
        preparator.prepare(mol)
        pdbqt_string = preparator.write_pdbqt_string()
        
        # Extract the molecule name from the SDF file
        mol_name = mol.GetProp('_Name')

        # Create the output file path
        output_path = os.path.join(output_dir, f"{mol_name}.pdbqt")

        # Write the pdbqt string to the file
        with open(output_path, 'w') as f:
            f.write(pdbqt_string)
    
from rdkit import Chem
from rdkit.Chem import AllChem
    
def load_molecule(molecule_file):
    """Load a molecule from a file.
    Parameters
    ----------
    molecule_file : str
        Path to file for storing a molecule, which can be of format '.mol2', '.mol', '.sdf',
        '.pdbqt', or '.pdb'.
    Returns
    -------
    mol : rdkit.Chem.rdchem.Mol
        RDKit molecule instance for the loaded molecule.
    """
    if molecule_file.endswith('.mol2'):
        mol = Chem.MolFromMol2File(molecule_file, sanitize=False, removeHs=False)
    if molecule_file.endswith('.mol'):
        mol = Chem.MolFromMolFile(molecule_file, sanitize=False, removeHs=False)
    elif molecule_file.endswith('.sdf'):
        supplier = Chem.SDMolSupplier(molecule_file, sanitize=False, removeHs=False)
        mol = supplier[0]
    elif molecule_file.endswith('.pdbqt'):
        with open(molecule_file) as f:
            pdbqt_data = f.readlines()
        pdb_block = ''
        for line in pdbqt_data:
            pdb_block += '{}\n'.format(line[:66])
        mol = Chem.MolFromPDBBlock(pdb_block, sanitize=False, removeHs=False)
    elif molecule_file.endswith('.pdb'):
        mol = Chem.MolFromPDBFile(molecule_file, sanitize=False, removeHs=False)
    else:
        return ValueError(f'Expect the format of the molecule_file to be '
                          'one of .mol2, .mol, .sdf, .pdbqt and .pdb, got {molecule_file}')
    return mol

import subprocess
from subprocess import DEVNULL, STDOUT

def convert_pdb_to_pdbqt(protein_file):
    # Define output file name
    pdbqt_file = protein_file.replace('.pdb', '.pdbqt')

    # Open Babel command
    obabel_command = f'obabel {protein_file} -O {pdbqt_file} -partialcharges Gasteiger -xr'

    # Execute command
    try:
        subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        print(f'Conversion from PDB to PDBQT failed: {e}')

    return pdbqt_file