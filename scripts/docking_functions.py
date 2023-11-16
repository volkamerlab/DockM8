from typing import Dict, Any, Union
from pandas import DataFrame
import os
import shutil
import subprocess
from subprocess import DEVNULL, STDOUT
import shutil
import pandas as pd
from rdkit.Chem import PandasTools
from IPython.display import display
import time
from scripts.utilities import *
import multiprocessing
from tqdm import tqdm
from pathlib import Path
import concurrent.futures
from scripts.utilities import load_molecule
import glob
from pathlib import Path
from meeko import PDBQTMolecule, RDKitMolCreate
from rdkit import Chem
from posebusters import PoseBusters
from yaml import safe_load

def qvinaw_docking(w_dir : Path, protein_file: str, pocket_definition : dict, software: str, exhaustiveness: int, n_poses: int) -> str:
    """
    Dock a library of molecules using the QVINAW software.

    Args:
        protein_file (str): Path to the protein file in PDB format.
        pocket_definition (dict): Dictionary containing the center and size of the docking pocket.
        software (str): Path to the QVINAW software folder.
        exhaustiveness (int): Level of exhaustiveness for the docking search.
        n_poses (int): Number of poses to generate for each ligand.

    Returns:
        str: Path to the combined docking results file in .sdf format.
    """
    printlog('Docking library using QVINAW...')
    tic = time.perf_counter()

    library = w_dir / 'final_library.sdf'
    qvinaw_folder = w_dir / 'qvinaw'
    pdbqt_files_folder = qvinaw_folder / 'pdbqt_files'
    pdbqt_files_folder.mkdir(parents=True, exist_ok=True)
    results_path = qvinaw_folder / 'docked'
    results_path.mkdir(parents=True, exist_ok=True)

    # Convert the protein file to .pdbqt format
    protein_file_pdbqt = convert_pdb_to_pdbqt(protein_file)

    try:
        print('Converting molecules to .pdbqt using Meeko')
        meeko_to_pdbqt(str(library), str(pdbqt_files_folder))
    except Exception as e:
        print('Failed to convert sdf file to .pdbqt')
        print(e)

    pdbqt_files = list(pdbqt_files_folder.glob('*.pdbqt'))

    # Dock each ligand in the library using QVINAW
    for pdbqt_file in tqdm(pdbqt_files, desc='Docking with QVINAW', total=len(pdbqt_files)):
        qvinaw_cmd = (
            f"{software / 'qvina-w'}"
            f" --receptor {protein_file_pdbqt}"
            f" --ligand {pdbqt_file}"
            f" --out {str(pdbqt_file).replace('pdbqt_files', 'docked')}"
            f" --center_x {pocket_definition['center'][0]}"
            f" --center_y {pocket_definition['center'][1]}"
            f" --center_z {pocket_definition['center'][2]}"
            f" --size_x {pocket_definition['size'][0]}"
            f" --size_y {pocket_definition['size'][1]}"
            f" --size_z {pocket_definition['size'][2]}"
            f" --exhaustiveness {exhaustiveness}"
            " --cpu 1"
            f" --num_modes {n_poses}"
        )
        try:
            subprocess.call(qvinaw_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('QVINAW docking failed: ' + e)

    toc = time.perf_counter()
    printlog(f'Docking with QVINAW complete in {toc-tic:0.4f}!')

    tic = time.perf_counter()
    qvinaw_docking_results = qvinaw_folder / 'qvinaw_poses.sdf'
    printlog('Fetching QVINAW poses...')

    results_pdbqt_files = results_path.glob('*.pdbqt')

    try:
        # Split PDBQT files by model
        for file in results_pdbqt_files:
            with open(file, 'r') as f:
                lines = f.readlines()

            models = []
            current_model = []
            for line in lines:
                current_model.append(line)
                if line.startswith('ENDMDL'):
                    models.append(current_model)
                    current_model = []

            for i, model in enumerate(models):
                for line in model:
                    if line.startswith('MODEL'):
                        model_number = int(line.split()[-1])
                        break
                output_filename = file.with_name(f"{file.stem}_QVINA2_{model_number}.pdbqt")
                with open(output_filename, 'w') as output_file:
                    output_file.writelines(model)
            os.remove(file)
            qvinaw_poses = pd.DataFrame(columns=['Pose ID', 'Molecule', 'QVINAW_Affinity'])
            for pose_file in results_path.glob('*.pdbqt'):
                pdbqt_mol = PDBQTMolecule.from_file(pose_file, name=pose_file.stem, skip_typing=True)
                rdkit_mol = RDKitMolCreate.from_pdbqt_mol(pdbqt_mol)
                qvinaw_poses = qvinaw_poses.append({
                    'Pose ID': pose_file.stem,
                    'Molecule': rdkit_mol[0],
                    'QVINAW_Affinity': next(line.split()[3] for line in open(pose_file) if 'REMARK VINA RESULT:' in line)
                    }, ignore_index=True)
            PandasTools.WriteSDF(qvinaw_poses,
                            str(qvinaw_docking_results),
                            molColName='Molecule',
                            idName='Pose ID',
                            properties=list(qvinaw_poses.columns))
    except Exception as e:
        printlog('ERROR: Failed to combine QVINAW SDF file!')
        printlog(e)
    else:
        shutil.rmtree(pdbqt_files_folder, ignore_errors=True)
        shutil.rmtree(results_path, ignore_errors=True)

    return str(qvinaw_docking_results)

def qvina2_docking(w_dir : Path, protein_file: str, pocket_definition : dict, software: str, exhaustiveness: int, n_poses: int) -> str:
    """
    Dock a library of molecules using QVINA2 software.

    Args:
        protein_file (str): Path to the protein file in PDB format.
        pocket_definition (dict): Dictionary containing the center and size of the docking pocket.
        software (str): Path to the QVINA2 software folder.
        exhaustiveness (int): Level of exhaustiveness for the docking search.
        n_poses (int): Number of poses to generate for each ligand.

    Returns:
        str: Path to the combined docking results file in .sdf format.
    """
    printlog('Docking library using QVINA2...')
    tic = time.perf_counter()
    
    library = w_dir / 'final_library.sdf'
    qvina2_folder = w_dir / 'qvina2'
    pdbqt_files_folder = qvina2_folder / 'pdbqt_files'
    pdbqt_files_folder.mkdir(parents=True, exist_ok=True)
    results_path = qvina2_folder / 'docked'
    results_path.mkdir(parents=True, exist_ok=True)
    
    # Convert the molecules in the library to .pdbqt format using the Meeko tool
    protein_file_pdbqt = convert_pdb_to_pdbqt(protein_file)
    try:
        print('Converting molecules to .pdbqt using Meeko')
        meeko_to_pdbqt(str(library), str(pdbqt_files_folder))
    except Exception as e:
        print('Failed to convert sdf file to .pdbqt')
        print(e)
    
    pdbqt_files = list(pdbqt_files_folder.glob('*.pdbqt'))
    
    # Perform docking using QVINA2 for each ligand in the library
    for pdbqt_file in tqdm(pdbqt_files, desc='Docking with QVINA2', total=len(pdbqt_files)):
        qvina2_cmd = (
            f"{software / 'qvina2.1'}"
            f" --receptor {protein_file_pdbqt}"
            f" --ligand {pdbqt_file}"
            f" --out {str(pdbqt_file).replace('pdbqt_files', 'docked')}"
            f" --center_x {pocket_definition['center'][0]}"
            f" --center_y {pocket_definition['center'][1]}"
            f" --center_z {pocket_definition['center'][2]}"
            f" --size_x {pocket_definition['size'][0]}"
            f" --size_y {pocket_definition['size'][1]}"
            f" --size_z {pocket_definition['size'][2]}"
            f" --exhaustiveness {exhaustiveness}"
            " --cpu 1"
            f" --num_modes {n_poses}"
        )
        try:
            subprocess.call(qvina2_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('QVINA2 docking failed: ' + e)
    
    toc = time.perf_counter()
    printlog(f'Docking with QVINA2 complete in {toc-tic:0.4f}!')
    tic = time.perf_counter()
    printlog('Fetching QVINA2 poses...')
    
    results_pdbqt_files = results_path.glob('*.pdbqt')
    qvina2_docking_results = qvina2_folder / 'qvina2_poses.sdf'
    results_pdbqt_files = list(results_path.glob('*.pdbqt'))
    try:
        # Split PDBQT files by model
        for file in results_pdbqt_files:
            with open(file, 'r') as f:
                lines = f.readlines()

            models = []
            current_model = []
            for line in lines:
                current_model.append(line)
                if line.startswith('ENDMDL'):
                    models.append(current_model)
                    current_model = []

            for i, model in enumerate(models):
                for line in model:
                    if line.startswith('MODEL'):
                        model_number = int(line.split()[-1])
                        break
                output_filename = file.with_name(f"{file.stem}_QVINA2_{model_number}.pdbqt")
                with open(output_filename, 'w') as output_file:
                    output_file.writelines(model)
            os.remove(file)
            qvina2_poses = pd.DataFrame(columns=['Pose ID', 'Molecule', 'QVINA2_Affinity'])
            for pose_file in results_path.glob('*.pdbqt'):
                pdbqt_mol = PDBQTMolecule.from_file(pose_file, name=pose_file.stem, skip_typing=True)
                rdkit_mol = RDKitMolCreate.from_pdbqt_mol(pdbqt_mol)
                qvina2_poses = qvina2_poses.append({
                    'Pose ID': pose_file.stem,
                    'Molecule': rdkit_mol[0],
                    'QVINA2_Affinity': next(line.split()[3] for line in open(pose_file) if 'REMARK VINA RESULT:' in line)
                    }, ignore_index=True)
            PandasTools.WriteSDF(qvina2_poses,
                            str(qvina2_docking_results),
                            molColName='Molecule',
                            idName='Pose ID',
                            properties=list(qvina2_poses.columns))
    except Exception as e:
        printlog('ERROR: Failed to combine QVINA2 SDF file!')
        printlog(e)
    else:
        shutil.rmtree(pdbqt_files_folder, ignore_errors=True)
        shutil.rmtree(results_path, ignore_errors=True)
    
    return str(qvina2_docking_results)

def smina_docking(w_dir : Path, protein_file: str, pocket_definition : dict, software: str, exhaustiveness: int, n_poses: int) -> str:
    '''
    Perform docking using the SMINA software on a protein and a reference ligand, and return the path to the results.

    Args:
    protein_file (str): path to the protein file in PDB format
    pocket_definition (dict): dictionary containing the center and size of the docking pocket
    software (str): path to the software folder
    exhaustiveness (int): level of exhaustiveness for the docking search, ranges from 0-8
    n_poses (int): number of poses to be generated

    Returns:
    results_path (str): the path to the results file in SDF format
    '''
    printlog('Docking library using SMINA...')
    tic = time.perf_counter()
    library = w_dir / 'final_library.sdf'
    smina_folder = w_dir / 'smina'
    smina_folder.mkdir(parents=True, exist_ok=True)
    results_path = smina_folder / 'docked.sdf'
    log = smina_folder / 'log.txt'
    smina_cmd = (
        f"{software / 'gnina'}" +
        f" --receptor {protein_file}" +
        f" --ligand {library}" +
        f" --out {results_path}" +
        f" --center_x {pocket_definition['center'][0]}" +
        f" --center_y {pocket_definition['center'][1]}" +
        f" --center_z {pocket_definition['center'][2]}" +
        f" --size_x {pocket_definition['size'][0]}" +
        f" --size_y {pocket_definition['size'][1]}" +
        f" --size_z {pocket_definition['size'][2]}" +
        f" --exhaustiveness {exhaustiveness}" +
        " --cpu 1" +
        f" --num_modes {n_poses}" +
        f" --log {log}" +
        " --cnn_scoring none --no_gpu"
    )
    try:
        subprocess.call(smina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        printlog('SMINA docking failed: ' + e)
    toc = time.perf_counter()
    printlog(f'Docking with SMINA complete in {toc-tic:0.4f}!')

    tic = time.perf_counter()
    printlog('Fetching SMINA poses...')
    try:
        smina_df = PandasTools.LoadSDF(str(results_path),
                                        idName='ID',
                                        molColName='Molecule',
                                        includeFingerprints=False,
                                        embedProps=False,
                                        removeHs=False,
                                        strictParsing=True)
        list_ = [*range(1, int(n_poses) + 1, 1)]
        ser = list_ * (len(smina_df) // len(list_))
        smina_df['Pose ID'] = [f'{row["ID"]}_SMINA_{num}' for num, (_,row) in zip(ser +list_[:len(smina_df) - len(ser)], smina_df.iterrows())]
        smina_df.rename(columns={'minimizedAffinity': 'SMINA_Affinity'},inplace=True)
    except Exception as e:
        printlog('ERROR: Failed to Load SMINA poses SDF file!')
        printlog(e)
    try:
        PandasTools.WriteSDF(smina_df,
                             str(smina_folder / 'smina_poses.sdf'),
                             molColName='Molecule',
                             idName='Pose ID',
                             properties=list(smina_df.columns))
        toc = time.perf_counter()
        printlog(f'Cleaned up SMINA poses in {toc-tic:0.4f}!')
    except Exception as e:
        printlog('ERROR: Failed to Write SMINA poses SDF file!')
        printlog(e)
    return str(smina_folder / 'smina_poses.sdf')

def gnina_docking(w_dir : Path, protein_file, pocket_definition, software, exhaustiveness, n_poses):
    '''
    Perform docking using the GNINA software on a protein and a reference ligand, and return the path to the results.

    Args:
    protein_file (str): path to the protein file in PDB format
    ref_file (str): path to the reference ligand file in SDF format
    software (str): path to the software folder
    exhaustiveness (int): level of exhaustiveness for the docking search, ranges from 0-8
    n_poses (int): number of poses to be generated

    Returns:
    results_path (str): the path to the results file in SDF format
    '''
    printlog('Docking library using GNINA...')
    tic = time.perf_counter()

    library = w_dir / 'final_library.sdf'
    gnina_folder = w_dir / 'gnina'
    gnina_folder.mkdir(parents=True, exist_ok=True)
    results_path = gnina_folder / 'docked.sdf'
    log = gnina_folder / 'log.txt'
    gnina_cmd = (
        f"{software / 'gnina'}" +
        f" --receptor {protein_file}" +
        f" --ligand {library}" +
        f" --out {results_path}" +
        f" --center_x {pocket_definition['center'][0]}" +
        f" --center_y {pocket_definition['center'][1]}" +
        f" --center_z {pocket_definition['center'][2]}" +
        f" --size_x {pocket_definition['size'][0]}" +
        f" --size_y {pocket_definition['size'][1]}" +
        f" --size_z {pocket_definition['size'][2]}" +
        f" --exhaustiveness {exhaustiveness}" +
        " --cpu 1" +
        f" --num_modes {n_poses}" +
        f" --log {log}" +
        " --cnn_scoring rescore --cnn crossdock_default2018 --no_gpu"
    )
    try:
        subprocess.call(gnina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        printlog('GNINA docking failed: ' + e)
    toc = time.perf_counter()
    printlog(f'Docking with GNINA complete in {toc-tic:0.4f}!')

    tic = time.perf_counter()
    printlog('Fetching GNINA poses...')
    try:
        gnina_df = PandasTools.LoadSDF(str(results_path),
                                        idName='ID',
                                        molColName='Molecule',
                                        includeFingerprints=False,
                                        embedProps=False,
                                        removeHs=False,
                                        strictParsing=True)
        list_ = [*range(1, int(n_poses) + 1, 1)]
        ser = list_ * (len(gnina_df) // len(list_))
        gnina_df['Pose ID'] = [f'{row["ID"]}_GNINA_{num}' for num, (_,row) in zip(ser + list_[:len(gnina_df) - len(ser)], gnina_df.iterrows())]
        gnina_df.rename(columns={'minimizedAffinity': 'GNINA_Affinity'}, inplace=True)
    except Exception as e:
        printlog('ERROR: Failed to Load GNINA poses SDF file!')
        printlog(e)
    try:
        PandasTools.WriteSDF(gnina_df,
                             str(gnina_folder / 'gnina_poses.sdf'),
                             molColName='Molecule',
                             idName='Pose ID',
                             properties=list(gnina_df.columns))
        toc = time.perf_counter()
        printlog(f'Cleaned up GNINA poses in {toc-tic:0.4f}!')
    except Exception as e:
        printlog('ERROR: Failed to Write GNINA poses SDF file!')
        printlog(e)
    return str(gnina_folder / 'gnina_poses.sdf')

def plants_docking(w_dir : Path, protein_file, pocket_definition, software, n_poses):
    '''
    Perform docking using the PLANTS software on a protein and a reference ligand, and return the path to the results.

    Args:
    protein_file (str): path to the protein file in PDB format
    ref_file (str): path to the reference ligand file in SDF format
    software (str): path to the software folder
    exhaustiveness (int): level of exhaustiveness for the docking search, ranges from 0-8
    n_poses (int): number of poses to be generated

    Returns:
    results_path (str): the path to the results file in SDF format
    '''
    printlog('Docking library using PLANTS...')
    tic = time.perf_counter()

    # Define initial variables
    plants_folder = w_dir / 'plants'
    plants_folder.mkdir(parents=True, exist_ok=True)
    # Convert protein file to .mol2 using open babel
    plants_protein_mol2 = w_dir / 'plants' / 'protein.mol2'
    try:
        printlog('Converting protein file to .mol2 format for PLANTS docking...')
        obabel_command = 'obabel -ipdb ' + \
            str(protein_file) + ' -O ' + str(plants_protein_mol2)
        subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        printlog('ERROR: Failed to convert protein file to .mol2!')
        printlog(e)
    # Convert prepared ligand file to .mol2 using open babel
    library = w_dir / 'final_library.sdf'
    plants_library_mol2 = plants_folder / 'ligands.mol2'
    try:
        obabel_command = 'obabel -isdf ' + \
            str(library) + ' -O ' + str(plants_library_mol2)
        os.system(obabel_command)
    except Exception as e:
        printlog('ERROR: Failed to convert docking library file to .mol2!')
        printlog(e)
    # Generate plants config file
    plants_docking_config_path = plants_folder / 'config.config'
    plants_config = ['# search algorithm\n',
                     'search_speed speed1\n',
                     'aco_ants 20\n',
                     'flip_amide_bonds 0\n',
                     'flip_planar_n 1\n',
                     'force_flipped_bonds_planarity 0\n',
                     'force_planar_bond_rotation 1\n',
                     'rescore_mode simplex\n',
                     'flip_ring_corners 0\n',
                     '# scoring functions\n',
                     '# Intermolecular (protein-ligand interaction scoring)\n',
                     'scoring_function chemplp\n',
                     'outside_binding_site_penalty 50.0\n',
                     'enable_sulphur_acceptors 1\n',
                     '# Intramolecular ligand scoring\n',
                     'ligand_intra_score clash2\n',
                     'chemplp_clash_include_14 1\n',
                     'chemplp_clash_include_HH 0\n',

                     '# input\n',
                     'protein_file ' + str(plants_protein_mol2) + '\n',
                     'ligand_file ' + str(plants_library_mol2) + '\n',

                     '# output\n',
                     'output_dir ' + str(plants_folder / 'results') + '\n',

                     '# write single mol2 files (e.g. for RMSD calculation)\n',
                     'write_multi_mol2 1\n',

                     '# binding site definition\n',
                     'bindingsite_center ' + str(pocket_definition['center'][0]) + ' ' + str(pocket_definition['center'][1]) + ' ' + str(pocket_definition['center'][2]) + '\n',
                     'bindingsite_radius ' + str(pocket_definition['size'][0] / 2) + '\n',

                     '# cluster algorithm\n',
                     'cluster_structures ' + str(n_poses) + '\n',
                     'cluster_rmsd 2.0\n',

                     '# write\n',
                     'write_ranking_links 0\n',
                     'write_protein_bindingsite 0\n',
                     'write_protein_conformations 0\n',
                     'write_protein_splitted 0\n',
                     'write_merged_protein 0\n',
                     '####\n']
    # Write config file
    printlog('Writing PLANTS config file...')
    with plants_docking_config_path.open('w') as configwriter:
        configwriter.writelines(plants_config)
    # Run PLANTS docking
    try:
        printlog('Starting PLANTS docking...')
        plants_docking_command = f'{software / "PLANTS"} --mode screen ' + str(plants_docking_config_path)
        subprocess.call(plants_docking_command, shell=True, stdout=DEVNULL, stderr=STDOUT) 
    except Exception as e:
        printlog('ERROR: PLANTS docking command failed...')
        printlog(e)
    plants_docking_results_mol2 = plants_folder / 'results' / 'docked_ligands.mol2'
    plants_docking_results_sdf = plants_docking_results_mol2.with_suffix('.sdf')
    # Convert PLANTS poses to sdf
    try:
        printlog('Converting PLANTS poses to .sdf format...')
        obabel_command = 'obabel -imol2 ' + str(plants_docking_results_mol2) + ' -O ' + str(plants_docking_results_sdf)
        subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        printlog('ERROR: Failed to convert PLANTS poses file to .sdf!')
        printlog(e)
    toc = time.perf_counter()
    printlog(f'Docking with PLANTS complete in {toc-tic:0.4f}!')
    plants_scoring_results = plants_folder / 'results' / 'ranking.csv'
    # Fetch PLANTS poses
    printlog('Fetching PLANTS poses...')
    try:
        plants_poses = PandasTools.LoadSDF(str(plants_docking_results_sdf),
                                            idName='ID',
                                            molColName='Molecule',
                                            includeFingerprints=False,
                                            embedProps=False,
                                            removeHs=False,
                                            strictParsing=True)
        plants_scores = pd.read_csv(str(plants_scoring_results), usecols=['LIGAND_ENTRY', 'TOTAL_SCORE'])
        plants_scores = plants_scores.rename(columns={'LIGAND_ENTRY': 'ID', 
                                                      'TOTAL_SCORE': 'CHEMPLP'})
        plants_scores = plants_scores[['ID', 'CHEMPLP']]
        plants_df = pd.merge(plants_scores, plants_poses, on='ID')
        plants_df['Pose ID'] = plants_df['ID'].str.split('_').str[0] + '_PLANTS_' + plants_df['ID'].str.split('_').str[4]
        plants_df['ID'] = plants_df['ID'].str.split('_').str[0]
    except Exception as e:
        printlog('ERROR: Failed to Load PLANTS poses SDF file!')
        printlog(e)
    try:
        PandasTools.WriteSDF(plants_df,
                             str(plants_folder / 'plants_poses.sdf'),
                             molColName='Molecule',
                             idName='Pose ID',
                             properties=list(plants_df.columns))
        shutil.rmtree(plants_folder / 'results', ignore_errors=True)
        files = 'software/'.glob('*.pid')
        for file in files:
            file.unlink()
        toc = time.perf_counter()
        printlog(f'Cleaned up PLANTS poses in {toc-tic:0.4f}!')
    except Exception as e:
        printlog('ERROR: Failed to Write PLANTS poses SDF file!')
        printlog(e)
    return str(plants_folder / 'plants_poses.sdf')

def smina_docking_splitted(split_file: str, w_dir: Path, protein_file: str, pocket_definition: Dict[str, list], software: Path, exhaustiveness: int, n_poses: int) -> None:
    """
    Dock ligands from a splitted file into a protein using smina.

    Args:
        split_file (str): Path to the splitted file containing the ligands to dock.
        protein_file (str): Path to the protein file.
        pocket_definition (Dict[str, list]): Dictionary containing the center and size of the pocket to dock into.
        software (Path): Path to the smina software.
        exhaustiveness (int): Exhaustiveness parameter for smina.
        n_poses (int): Number of poses to generate.

    Returns:
        None
    """

    smina_folder = w_dir / 'smina'
    smina_folder.mkdir(parents=True, exist_ok=True)
    results_path = smina_folder / f"{os.path.basename(split_file).split('.')[0]}_smina.sdf"
    smina_cmd = (
        f'{software / "gnina"}' +
        f' --receptor {protein_file}' +
        f' --ligand {split_file}' +
        f' --out {results_path}' +
        f' --center_x {pocket_definition["center"][0]}' +
        f' --center_y {pocket_definition["center"][1]}' +
        f' --center_z {pocket_definition["center"][2]}' +
        f' --size_x {pocket_definition["size"][0]}' +
        f' --size_y {pocket_definition["size"][1]}' +
        f' --size_z {pocket_definition["size"][2]}' +
        f' --exhaustiveness {exhaustiveness}' +
        ' --cpu 1' +
        f' --num_modes {n_poses}' +
        ' --cnn_scoring none --no_gpu'
    )
    try:
        subprocess.call(smina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        printlog(f'SMINA docking failed: {e}')
    return

def gnina_docking_splitted(split_file: str, w_dir: Path, protein_file: str, pocket_definition: Dict[str, list], software: str, exhaustiveness: int, n_poses: int) -> None:
    """
    Dock ligands from a splitted file into a protein using GNINA software.

    Args:
        split_file (str): Path to the splitted file containing the ligands to dock.
        protein_file (str): Path to the protein file.
        pocket_definition (Dict[str, list]): Dictionary containing the center and size of the pocket to dock into.
        software (str): Path to the GNINA software.
        exhaustiveness (int): Exhaustiveness parameter for GNINA.
        n_poses (int): Number of poses to generate.

    Returns:
        None
    """

    gnina_folder = w_dir / 'gnina'
    gnina_folder.mkdir(parents=True, exist_ok=True)
    results_path = gnina_folder / f"{os.path.basename(split_file).split('.')[0]}_gnina.sdf"
    gnina_cmd = (
        f"{software / 'gnina'}" +
        f" --receptor {protein_file}" +
        f" --ligand {split_file}" +
        f" --out {results_path}" +
        f" --center_x {pocket_definition['center'][0]}" +
        f" --center_y {pocket_definition['center'][1]}" +
        f" --center_z {pocket_definition['center'][2]}" +
        f" --size_x {pocket_definition['size'][0]}" +
        f" --size_y {pocket_definition['size'][1]}" +
        f" --size_z {pocket_definition['size'][2]}" +
        f" --exhaustiveness {exhaustiveness}" +
        " --cpu 1" +
        f" --num_modes {n_poses}" +
        " --cnn_scoring rescore --cnn crossdock_default2018 --no_gpu"
    )

    try:
        subprocess.call(gnina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
    except Exception as e:
        printlog(f"GNINA docking failed: {e}")
    return

def plants_docking_splitted(split_file: Path, w_dir: Path, n_poses: int, pocket_definition: Dict[str, list], software: Path) -> None:
    """
    Runs PLANTS docking on a splitted file.

    Args:
        split_file (Path): The path to the splitted file.
        w_dir (Path): The working directory.
        n_poses (int): The number of poses to cluster.
        pocket_definition (Dict[str, list]): The pocket definition.
        software (Path): The path to the PLANTS software.

    Returns:
        None
    """
    plants_docking_results_dir = w_dir / 'plants' / ('results_' + split_file.stem)
    # Generate plants config file
    plants_docking_config_path = w_dir / 'plants' / ('config_' + split_file.stem + '.config')
    plants_config = ['# search algorithm\n',
                     'search_speed speed1\n',
                     'aco_ants 20\n',
                     'flip_amide_bonds 0\n',
                     'flip_planar_n 1\n',
                     'force_flipped_bonds_planarity 0\n',
                     'force_planar_bond_rotation 1\n',
                     'rescore_mode simplex\n',
                     'flip_ring_corners 0\n',
                     '# scoring functions\n',
                     '# Intermolecular (protein-ligand interaction scoring)\n',
                     'scoring_function chemplp\n',
                     'outside_binding_site_penalty 50.0\n',
                     'enable_sulphur_acceptors 0\n',
                     '# Intramolecular ligand scoring\n',
                     'ligand_intra_score clash2\n',
                     'chemplp_clash_include_14 1\n',
                     'chemplp_clash_include_HH 0\n',

                     '# input\n',
                     'protein_file ' + str(w_dir / 'plants' / 'protein.mol2') + '\n',
                     'ligand_file ' + str(w_dir / 'plants' / os.path.basename(split_file).replace('.sdf', '.mol2')) + '\n',

                     '# output\n',
                     'output_dir ' + str(plants_docking_results_dir) + '\n',

                     '# write single mol2 files (e.g. for RMSD calculation)\n',
                     'write_multi_mol2 1\n',

                     '# binding site definition\n',
                     'bindingsite_center ' + str(pocket_definition['center'][0]) + ' ' + str(pocket_definition['center'][1]) + ' ' + str(pocket_definition['center'][2]) + '+\n',
                     'bindingsite_radius ' + str(pocket_definition['size'][0] / 2) + '\n',

                     '# cluster algorithm\n',
                     'cluster_structures ' + str(n_poses) + '\n',
                     'cluster_rmsd 2.0\n',

                     '# write\n',
                     'write_ranking_links 0\n',
                     'write_protein_bindingsite 0\n',
                     'write_protein_conformations 0\n',
                     'write_protein_splitted 0\n',
                     'write_merged_protein 0\n',
                     '####\n']
    # Write config file
    try:
        with open(plants_docking_config_path, 'w') as configwriter:
                configwriter.writelines(plants_config)
    except Exception as e:
        printlog(f'ERROR: Could not write PLANTS config file : {e}')
    # Run PLANTS docking
    try:
        plants_docking_command = f'{software / "PLANTS"} --mode screen ' + str(plants_docking_config_path)
        subprocess.call(plants_docking_command,shell=True, stdout=DEVNULL,stderr=STDOUT)
    except Exception as e:
        printlog('ERROR: PLANTS docking command failed...')
        printlog(e)
    return
def qvinaw_docking_splitted(split_file: Path, w_dir: Path, protein_file_pdbqt: Path, pocket_definition: Dict[str, list], software: Path, exhaustiveness: int, n_poses: int):
    """
    Dock ligands from a split file to a protein using QVINAW.

    Args:
    - split_file (str): Path to the split file containing the ligands to dock.
    - protein_file_pdbqt (str): Path to the protein file in pdbqt format.
    - pocket_definition (dict): Dictionary containing the center and size of the pocket to dock to.
    - software (pathlib.Path): Path to the QVINAW software.
    - exhaustiveness (int): Exhaustiveness parameter for QVINAW.
    - n_poses (int): Number of poses to generate for each ligand.

    Returns:
    - qvinaw_docking_results (pathlib.Path): Path to the resulting SDF file containing the docked poses.
    """

    qvinaw_folder = w_dir / 'qvinaw'
    pdbqt_files_folder = qvinaw_folder / Path(split_file).stem / 'pdbqt_files'
    pdbqt_files_folder.mkdir(parents=True, exist_ok=True)
    results_path = qvinaw_folder / Path(split_file).stem / 'docked'
    results_path.mkdir(parents=True, exist_ok=True)

    try:
        meeko_to_pdbqt(str(split_file), str(pdbqt_files_folder))
    except Exception as e:
        print('Failed to convert sdf file to .pdbqt')
        print(e)

    pdbqt_files = list(pdbqt_files_folder.glob('*.pdbqt'))

    for pdbqt_file in pdbqt_files:
        qvina_cmd = (
            f"{software / 'qvina-w'}" +
            f" --receptor {protein_file_pdbqt}" +
            f" --ligand {pdbqt_file}" +
            f" --out {str(pdbqt_file).replace('pdbqt_files', 'docked')}" +
            f" --center_x {pocket_definition['center'][0]}" +
            f" --center_y {pocket_definition['center'][1]}" +
            f" --center_z {pocket_definition['center'][2]}" +
            f" --size_x {pocket_definition['size'][0]}" +
            f" --size_y {pocket_definition['size'][1]*2}" +
            f" --size_z {pocket_definition['size'][2]*2}" +
            f" --exhaustiveness {exhaustiveness}" +
            " --cpu 1" +
            f" --num_modes {n_poses}"
        )
        try:
            subprocess.call(qvina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('QVINAW docking failed: ' + e)

    qvinaw_docking_results = qvinaw_folder / (Path(split_file).stem + '_qvinaw.sdf')

    results_pdbqt_files = list(results_path.glob('*.pdbqt'))
    try:
        for file in results_pdbqt_files:
            with open(file, 'r') as f:
                lines = f.readlines()
            models = []
            current_model = []
            for line in lines:
                current_model.append(line)
                if line.startswith('ENDMDL'):
                    models.append(current_model)
                    current_model = []
            for i, model in enumerate(models):
                for line in model:
                    if line.startswith('MODEL'):
                        model_number = int(line.split()[-1])
                        break
                output_filename = file.with_name(f"{file.stem}_QVINAW_{model_number}.pdbqt")
                with open(output_filename, 'w') as output_file:
                    output_file.writelines(model)
            os.remove(file)
        qvinaw_poses = pd.DataFrame(columns=['Pose ID', 'Molecule', 'QVINAW_Affinity'])
        for pose_file in results_path.glob('*.pdbqt'):
            pdbqt_mol = PDBQTMolecule.from_file(pose_file, name=pose_file.stem, skip_typing=True)
            rdkit_mol = RDKitMolCreate.from_pdbqt_mol(pdbqt_mol)
            qvinaw_poses = qvinaw_poses.append({
                'Pose ID': pose_file.stem,
                'Molecule': rdkit_mol[0],
                'QVINAW_Affinity': next(line.split()[3] for line in open(pose_file) if 'REMARK VINA RESULT:' in line)
                }, ignore_index=True)
        PandasTools.WriteSDF(qvinaw_poses,
                        str(qvinaw_docking_results),
                        molColName='Molecule',
                        idName='Pose ID',
                        properties=list(qvinaw_poses.columns))
    except Exception as e:
        printlog('ERROR: Failed to combine QVINAW SDF file!')
        printlog(e)
    else:
        shutil.rmtree(qvinaw_folder / Path(split_file).stem, ignore_errors=True)
    return qvinaw_docking_results

def qvina2_docking_splitted(split_file: Path, w_dir: Path, protein_file_pdbqt: Path, pocket_definition: Dict[str, list], software: Path, exhaustiveness: int, n_poses: int):
    """
    Dock ligands from a split file to a protein using QVina2.

    Args:
    - split_file (str): Path to the split file containing the ligands to dock.
    - protein_file_pdbqt (str): Path to the protein file in pdbqt format.
    - pocket_definition (dict): Dictionary containing the center and size of the pocket to dock to.
    - software (pathlib.Path): Path to the QVina2 software.
    - exhaustiveness (int): Exhaustiveness parameter for QVina2.
    - n_poses (int): Number of poses to generate for each ligand.

    Returns:
    - qvina2_docking_results (pathlib.Path): Path to the SDF file containing the docking results.
    """

    qvina2_folder = w_dir / 'qvina2'
    pdbqt_files_folder = qvina2_folder / Path(split_file).stem / 'pdbqt_files'
    pdbqt_files_folder.mkdir(parents=True, exist_ok=True)
    results_path = qvina2_folder / Path(split_file).stem / 'docked'
    results_path.mkdir(parents=True, exist_ok=True)

    try:
        meeko_to_pdbqt(str(split_file), str(pdbqt_files_folder))
    except Exception as e:
        print('Failed to convert sdf file to .pdbqt')
        print(e)

    pdbqt_files = list(pdbqt_files_folder.glob('*.pdbqt'))

    for pdbqt_file in pdbqt_files:
        qvina_cmd = (f"{software / 'qvina2.1'}" +
                    f" --receptor {protein_file_pdbqt}" +
                    f" --ligand {pdbqt_file}" +
                    f" --out {str(pdbqt_file).replace('pdbqt_files', 'docked')}" +
                    f" --center_x {pocket_definition['center'][0]}" +
                    f" --center_y {pocket_definition['center'][1]}" +
                    f" --center_z {pocket_definition['center'][2]}" +
                    f" --size_x {pocket_definition['size'][0]}" +
                    f" --size_y {pocket_definition['size'][1]*2}" +
                    f" --size_z {pocket_definition['size'][2]*2}" +
                    f" --exhaustiveness {exhaustiveness}" +
                    " --cpu 1" +
                    f" --num_modes {n_poses}"
        )

        try:
            subprocess.call(qvina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('QVINA2 docking failed: ' + e)

    qvina2_docking_results = qvina2_folder / (Path(split_file).stem + '_qvina2.sdf')

    results_pdbqt_files = list(results_path.glob('*.pdbqt'))
    try:
        # Split PDBQT files by model
        for file in results_pdbqt_files:
            with open(file, 'r') as f:
                lines = f.readlines()
            models = []
            current_model = []
            for line in lines:
                current_model.append(line)
                if line.startswith('ENDMDL'):
                    models.append(current_model)
                    current_model = []
            for i, model in enumerate(models):
                for line in model:
                    if line.startswith('MODEL'):
                        model_number = int(line.split()[-1])
                        break
                output_filename = file.with_name(f"{file.stem}_QVINA2_{model_number}.pdbqt")
                with open(output_filename, 'w') as output_file:
                    output_file.writelines(model)
            os.remove(file)
            qvina2_poses = pd.DataFrame(columns=['Pose ID', 'Molecule', 'QVINA2_Affinity'])
            for pose_file in results_path.glob('*.pdbqt'):
                pdbqt_mol = PDBQTMolecule.from_file(pose_file, name=pose_file.stem, skip_typing=True)
                rdkit_mol = RDKitMolCreate.from_pdbqt_mol(pdbqt_mol)
                qvina2_poses = qvina2_poses.append({
                    'Pose ID': pose_file.stem,
                    'Molecule': rdkit_mol[0],
                    'QVINA2_Affinity': next(line.split()[3] for line in open(pose_file) if 'REMARK VINA RESULT:' in line)
                    }, ignore_index=True)
            PandasTools.WriteSDF(qvina2_poses,
                            str(qvina2_docking_results),
                            molColName='Molecule',
                            idName='Pose ID',
                            properties=list(qvina2_poses.columns))
    except Exception as e:
        printlog('ERROR: Failed to combine QVINA2 SDF file!')
        printlog(e)
    else:
        shutil.rmtree(qvina2_folder / Path(split_file).stem, ignore_errors=True)
    return qvina2_docking_results

def docking(w_dir : str or Path, protein_file : str or Path, pocket_definition: Dict[str, list], software : str or Path, docking_programs : list, exhaustiveness : int, n_poses : int, ncpus : int):
    """
    Dock ligands into a protein binding site using one or more docking programs.

    Parameters:
    -----------
    w_dir : str or Path
        Working directory where the docking results will be saved.
    protein_file : str or Path
        Path to the protein file in PDB format.
    pocket_definition : str or Path
        Path to the file with the pocket definition in PDB format.
    software : str
        Name of the software used for docking (e.g. AutoDock Vina, PLANTS).
    docking_programs : list of str
        List of docking programs to use (e.g. ['VINA', 'PLANTS']).
    exhaustiveness : int
        Exhaustiveness parameter for the docking program(s).
    n_poses : int
        Number of poses to generate for each ligand.
    ncpus : int
        Number of CPUs to use for parallel execution.

    Returns:
    --------
    None
    """
    if ncpus == 1:
        tic = time.perf_counter()
        if 'SMINA' in docking_programs and (w_dir / 'smina').is_dir() == False:
            smina_docking(w_dir, protein_file, pocket_definition, software,  exhaustiveness, n_poses)
        if 'GNINA' in docking_programs and (w_dir / 'gnina').is_dir() == False:
            gnina_docking(w_dir, protein_file, pocket_definition, software,  exhaustiveness, n_poses)
        if 'PLANTS' in docking_programs and (w_dir / 'plants').is_dir() == False:
            plants_docking(w_dir, protein_file, pocket_definition, software, n_poses)
        if 'QVINAW' in docking_programs and (w_dir / 'qvinaw').is_dir() == False:
            qvinaw_docking(w_dir, protein_file, pocket_definition, software,  exhaustiveness, n_poses)
        if 'QVINA2' in docking_programs and (w_dir / 'qvina2').is_dir() == False:
            qvina2_docking(w_dir, protein_file, pocket_definition, software,  exhaustiveness, n_poses)
        toc = time.perf_counter()
        printlog(f'Finished docking in {toc-tic:0.4f}!')
        
    else:
        split_final_library_path = w_dir / 'split_final_library'
        if not split_final_library_path.is_dir():
            split_files_folder = split_sdf(str(w_dir), str(w_dir / 'final_library.sdf'), ncpus)
        else:
            printlog('Split final library folder already exists...')
            split_files_folder = split_final_library_path
        split_files_sdfs = [(split_files_folder / f) for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
        if 'PLANTS' in docking_programs and not (w_dir / 'plants').is_dir():
            tic = time.perf_counter()
            plants_folder = w_dir / 'plants'
            plants_folder.mkdir(parents=True, exist_ok=True)
            # Convert protein file to .mol2 using open babel
            plants_protein_mol2 = plants_folder / 'protein.mol2'
            try:
                printlog('Converting protein file to .mol2 format for PLANTS docking...')
                obabel_command = f'obabel -ipdb {protein_file} -O {plants_protein_mol2}'
                subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
            except Exception as e:
                printlog('ERROR: Failed to convert protein file to .mol2!')
                printlog(e)
            # Convert prepared ligand file to .mol2 using open babel
            for file in os.listdir(split_files_folder):
                if file.endswith('.sdf'):
                    try:
                        obabel_command = f'obabel -isdf {split_files_folder}/{file} -O {w_dir / "plants"}/{Path(file).stem}.mol2'
                        subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
                    except Exception as e:
                        printlog(f'ERROR: Failed to convert {file} to .mol2!')
                        printlog(e)
            printlog('Docking split files using PLANTS...')
            
            res = parallel_executor_joblib(plants_docking_splitted, split_files_sdfs, ncpus, w_dir=w_dir, n_poses=n_poses, pocket_definition=pocket_definition, software=software)
            
            toc = time.perf_counter()
            printlog(f'Docking with PLANTS complete in {toc - tic:0.4f}!')
        # Fetch PLANTS poses
        if 'PLANTS' in docking_programs and (w_dir / 'plants').is_dir() and not (w_dir / 'plants' / 'plants_poses.sdf').is_file():
            plants_dataframes = []
            results_folders = [item for item in os.listdir(w_dir / 'plants')]
            for item in tqdm(results_folders, desc='Fetching PLANTS docking poses'):
                if item.startswith('results'):
                    file_path = w_dir / 'plants' / item / 'docked_ligands.mol2'
                    if file_path.is_file():
                        try:
                            obabel_command = f'obabel -imol2 {file_path} -O {file_path.with_suffix(".sdf")}'
                            subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
                            plants_poses = PandasTools.LoadSDF(str(file_path.with_suffix('.sdf')),
                                                                idName='ID',
                                                                molColName='Molecule',
                                                                includeFingerprints=False,
                                                                embedProps=False,
                                                                removeHs=False,
                                                                strictParsing=True)
                            plants_scores = pd.read_csv(str(file_path).replace('docked_ligands.mol2', 'ranking.csv')).rename(columns={'LIGAND_ENTRY': 'ID', 'TOTAL_SCORE': 'CHEMPLP'})[['ID', 'CHEMPLP']]
                            plants_df = pd.merge(plants_scores, plants_poses, on='ID')
                            plants_df['ID'] = plants_df['ID'].str.split('_').str[0]
                            list_ = [*range(1, int(n_poses) + 1, 1)]
                            ser = list_ * (len(plants_df) // len(list_))
                            plants_df['Pose ID'] = [f'{row["ID"]}_PLANTS_{num}' for num, (_, row) in zip(ser + list_[:len(plants_df) - len(ser)], plants_df.iterrows())]
                            plants_dataframes.append(plants_df)
                        except Exception as e:
                            printlog(
                                'ERROR: Failed to convert PLANTS docking results file to .sdf!')
                            printlog(e)
                elif item in ['protein.mol2', 'ref.mol2']:
                    pass
                else:
                    Path(w_dir / 'plants', item).unlink(missing_ok=True)
            try:
                plants_df = pd.concat(plants_dataframes)
                PandasTools.WriteSDF(plants_df,
                                     str(w_dir / 'plants' / 'plants_poses.sdf'),
                                     molColName='Molecule',
                                     idName='Pose ID',
                                     properties=list(plants_df.columns))
                files = Path(software).glob('*.pid')
                for file in files:
                    file.unlink()
            except Exception as e:
                printlog('ERROR: Failed to write combined PLANTS docking poses')
                printlog(e)
            else:
                delete_files(w_dir / 'plants', 'plants_poses.sdf')
        # Docking split files using SMINA
        if 'SMINA' in docking_programs and not (w_dir / 'smina').is_dir():
            printlog('Docking split files using SMINA...')
            tic = time.perf_counter()
            
            res = parallel_executor_joblib(smina_docking_splitted, 
                                            split_files_sdfs, 
                                            ncpus, 
                                            w_dir = w_dir,
                                            protein_file=protein_file,
                                            pocket_definition = pocket_definition,
                                            software = software,
                                            exhaustiveness = exhaustiveness,
                                            n_poses = n_poses)
            
            toc = time.perf_counter()
            printlog(f'Docking with SMINA complete in {toc - tic:0.4f}!')
        # Fetch SMINA poses
        if 'SMINA' in docking_programs and (w_dir / 'smina').is_dir() and not (w_dir / 'smina' / 'smina_poses.sdf').is_file():
            try:
                smina_dataframes = []
                for file in tqdm(os.listdir(w_dir / 'smina'), desc='Loading SMINA poses'):
                    if file.startswith('split'):
                        df = PandasTools.LoadSDF(str(w_dir / 'smina' / file),
                                                idName='ID',
                                                molColName='Molecule',
                                                includeFingerprints=False,
                                                embedProps=False,
                                                removeHs=False,
                                                strictParsing=True)
                        smina_dataframes.append(df)
                smina_df = pd.concat(smina_dataframes)
                list_ = [*range(1, int(n_poses) + 1, 1)]
                ser = list_ * (len(smina_df) // len(list_))
                smina_df['Pose ID'] = [f'{row["ID"]}_SMINA_{num}' for num, (_,row) in zip(ser + list_[ :len(smina_df) - len(ser)],smina_df.iterrows())]
                smina_df.rename(columns={'minimizedAffinity': 'SMINA_Affinity'}, inplace=True)
            except Exception as e:
                printlog('ERROR: Failed to Load SMINA poses SDF file!')
                printlog(e)
            try:
                PandasTools.WriteSDF(smina_df,
                                     str(w_dir / 'smina' / 'smina_poses.sdf'),
                                     molColName='Molecule',
                                     idName='Pose ID',
                                     properties=list(smina_df.columns))
            except Exception as e:
                printlog('ERROR: Failed to write combined SMINA poses SDF file!')
                printlog(e)
            else:
                delete_files(w_dir / 'smina', 'smina_poses.sdf')
        # Docking split files using GNINA
        if 'GNINA' in docking_programs and not (w_dir / 'gnina').is_dir():
            printlog('Docking split files using GNINA...')
            tic = time.perf_counter()
            
            res = parallel_executor_joblib(gnina_docking_splitted, 
                                            split_files_sdfs, 
                                            ncpus, 
                                            w_dir = w_dir,
                                            protein_file=protein_file,
                                            pocket_definition = pocket_definition,
                                            software = software,
                                            exhaustiveness = exhaustiveness,
                                            n_poses = n_poses)
            toc = time.perf_counter()
            printlog(f'Docking with GNINA complete in {toc - tic:0.4f}!')
        # Fetch GNINA poses
        if 'GNINA' in docking_programs and (w_dir / 'gnina').is_dir() and not (w_dir / 'gnina' / 'gnina_poses.sdf').is_file():
            try:
                gnina_dataframes = []
                for file in tqdm(os.listdir(w_dir / 'gnina'), desc='Loading GNINA poses'):
                    if file.startswith('split'):
                        df = PandasTools.LoadSDF(str(w_dir / 'gnina' / file),
                                                idName='ID',
                                                molColName='Molecule',
                                                includeFingerprints=False,
                                                embedProps=False,
                                                removeHs=False,
                                                strictParsing=True)
                        gnina_dataframes.append(df)
                gnina_df = pd.concat(gnina_dataframes)
                list_ = [*range(1, int(n_poses) + 1, 1)]
                ser = list_ * (len(gnina_df) // len(list_))
                gnina_df['Pose ID'] = [f'{row["ID"]}_GNINA_{num}' for num, (_, row) in zip( ser + list_[ :len(gnina_df) - len(ser)], gnina_df.iterrows())]
                gnina_df.rename(columns={'minimizedAffinity': 'GNINA_Affinity'}, inplace=True)
            except Exception as e:
                printlog('ERROR: Failed to Load GNINA poses SDF file!')
                printlog(e)
            try:
                PandasTools.WriteSDF(gnina_df,
                                     str(w_dir / 'gnina' / 'gnina_poses.sdf'),
                                     molColName='Molecule',
                                     idName='Pose ID',
                                     properties=list(gnina_df.columns))
            except Exception as e:
                printlog('ERROR: Failed to write combined GNINA docking poses')
                printlog(e)
            else:
                delete_files(w_dir / 'gnina', 'gnina_poses.sdf')
        # Docking split files using QVINAW
        if 'QVINAW' in docking_programs and not (w_dir / 'qvinaw').is_dir():
            printlog('Docking split files using QVINAW...')
            tic = time.perf_counter()
            protein_file_pdbqt = convert_pdb_to_pdbqt(protein_file)
            
            res = parallel_executor(qvinaw_docking_splitted, 
                                            split_files_sdfs, 
                                            ncpus, 
                                            w_dir = w_dir,
                                            protein_file_pdbqt=protein_file_pdbqt,
                                            pocket_definition = pocket_definition,
                                            software = software,
                                            exhaustiveness = exhaustiveness,
                                            n_poses = n_poses)
            
            toc = time.perf_counter()
            printlog(f'Docking with QVINAW complete in {toc - tic:0.4f}!')
        # Fetch QVINAW poses
        if 'QVINAW' in docking_programs and (w_dir / 'qvinaw').is_dir() and not (w_dir / 'qvinaw' / 'qvinaw_poses.sdf').is_file():
            try:
                qvinaw_dataframes = []
                for file in tqdm(os.listdir(w_dir / 'qvinaw'), desc='Loading QVINAW poses'):
                    if file.startswith('split'):
                        df = PandasTools.LoadSDF(str(w_dir / 'qvinaw' / file),
                                                idName='Pose ID',
                                                molColName='Molecule',
                                                includeFingerprints=False,
                                                embedProps=False,
                                                removeHs=False,
                                                strictParsing=True)
                        qvinaw_dataframes.append(df)
                qvinaw_df = pd.concat(qvinaw_dataframes)
            except Exception as e:
                printlog('ERROR: Failed to Load QVINAW poses SDF file!')
                printlog(e)
            try:
                PandasTools.WriteSDF(qvinaw_df,
                                     str(w_dir / 'qvinaw' / 'qvinaw_poses.sdf'),
                                     molColName='Molecule',
                                     idName='Pose ID',
                                     properties=list(qvinaw_df.columns))
            except Exception as e:
                printlog('ERROR: Failed to write combined QVINAW poses SDF file!')
                printlog(e)
            else:
                delete_files(w_dir / 'qvinaw', 'qvinaw_poses.sdf')
        # Docking split files using QVINA2
        if 'QVINA2' in docking_programs and not (w_dir / 'qvina2').is_dir():
            printlog('Docking split files using QVINA2...')
            tic = time.perf_counter()
            protein_file_pdbqt = convert_pdb_to_pdbqt(protein_file)
            
            res = parallel_executor_joblib(qvina2_docking_splitted, 
                                            split_files_sdfs, 
                                            ncpus, 
                                            w_dir = w_dir,
                                            protein_file_pdbqt=protein_file_pdbqt,
                                            pocket_definition = pocket_definition,
                                            software = software,
                                            exhaustiveness = exhaustiveness,
                                            n_poses = n_poses)
            toc = time.perf_counter()
            printlog(f'Docking with QVINA2 complete in {toc - tic:0.4f}!')
        # Fetch QVINA2 poses
        if 'QVINA2' in docking_programs and (w_dir / 'qvina2').is_dir() and not (w_dir / 'qvina2' / 'qvina2_poses.sdf').is_file():
            try:
                qvina2_dataframes = []
                for file in tqdm(os.listdir(w_dir / 'qvina2'), desc='Loading QVINA2 poses'):
                    if file.startswith('split'):
                        df = PandasTools.LoadSDF(str(w_dir / 'qvina2' / file),
                                                idName='Pose ID',
                                                molColName='Molecule',
                                                includeFingerprints=False,
                                                embedProps=False,
                                                removeHs=False,
                                                strictParsing=True)
                        qvina2_dataframes.append(df)
                qvina2_df = pd.concat(qvina2_dataframes)
            except Exception as e:
                printlog('ERROR: Failed to Load QVINA2 poses SDF file!')
                printlog(e)
            try:
                PandasTools.WriteSDF(qvina2_df,
                                     str(w_dir / 'qvina2' / 'qvina2_poses.sdf'),
                                     molColName='Molecule',
                                     idName='Pose ID',
                                     properties=list(qvina2_df.columns))
            except Exception as e:
                printlog('ERROR: Failed to write combined QVINA2 poses SDF file!')
                printlog(e)
            else:
                delete_files(w_dir / 'qvina2', 'qvina2_poses.sdf')
    shutil.rmtree(w_dir / 'split_final_library', ignore_errors=True)
    return

def concat_all_poses(w_dir, docking_programs, protein_file):
    """
    Concatenates all poses from the specified docking programs and checks them for quality using PoseBusters.
    
    Args:
    w_dir (str): Working directory where the docking program output files are located.
    docking_programs (list): List of strings specifying the names of the docking programs used.
    protein_file (str): Path to the protein file used for docking.
    
    Returns:
    None
    """
    all_poses = pd.DataFrame()
    for program in docking_programs:
        try:
            df = PandasTools.LoadSDF(f"{w_dir}/{program.lower()}/{program.lower()}_poses.sdf",
                                    idName='Pose ID',
                                    molColName='Molecule',
                                    includeFingerprints=False,
                                    embedProps=False,
                                    removeHs=False,
                                    strictParsing=True)
            all_poses = pd.concat([all_poses, df])
        except Exception as e:
            printlog(f'ERROR: Failed to load {program} SDF file!')
            printlog(e)
    try:
        start_time = time.time()
        buster = PoseBusters(config=safe_load(open('./scripts/posebusters_config.yml')))
        all_poses['mol_cond'] = str(protein_file)
        all_poses = all_poses.rename(columns={'Molecule':'mol_pred'})
        df = buster.bust_table(all_poses)
        # Remove rows where any of the specified columns is 'False'
        cols_to_check = ['all_atoms_connected', 'bond_lengths', 'bond_angles', 'internal_steric_clash', 'aromatic_ring_flatness', 'double_bond_flatness', 'protein-ligand_maximum_distance']
        df = df.loc[(df[cols_to_check] != False).all(axis=1)]
        df.reset_index(inplace=True)
        all_poses = all_poses[all_poses['Pose ID'].isin(df['molecule'])].rename(columns={'mol_pred':'Molecule'})  
        end_time = time.time()
        printlog(f"PoseBusters checking completed in {end_time - start_time:.2f} seconds.")
    except Exception as e:
        printlog('ERROR: Failed to check poses with PoseBusters!')     
        printlog(e)
    try:
        PandasTools.WriteSDF(all_poses,
                            f"{w_dir}/allposes.sdf",
                            molColName='Molecule',
                            idName='Pose ID',
                            properties=list(all_poses.columns))
        printlog('All poses succesfully checked and combined!')
    except Exception as e:
        printlog('ERROR: Failed to write all_poses SDF file!')        
        printlog(e)
    return
