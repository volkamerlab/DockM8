from typing import List, Tuple
from pandas import DataFrame
import os
import shutil
import subprocess
from subprocess import DEVNULL, STDOUT, PIPE
import pandas as pd
from rdkit import Chem
from rdkit.Chem import PandasTools
from tqdm import tqdm
import time
from scripts.utilities import *
from software.ECIF.ecif import *
import pickle
from functools import partial
from software.RTMScore.rtmscore_modified import *
from pathlib import Path
import glob

import time
import os
import subprocess
from pathlib import Path
from typing import List
from pandas import DataFrame
from rdkit.Chem import PandasTools
import pandas as pd
from scripts.utilities import parallel_executor, split_sdf, delete_files, printlog

def rescore_all(w_dir: str, protein_file: str, pocket_definition: dict, software: str, clustered_sdf: str, functions: List[str], ncpus: int) -> None:
    """
    Rescores ligand poses using the specified software and scoring functions. The function splits the input SDF file into
    smaller files, and then runs the specified software on each of these files in parallel. The results are then combined into a single
    Pandas dataframe and saved to a CSV file.

    Args:
        w_dir (str): The working directory.
        protein_file (str): The path to the protein file.
        pocket_definition (dict): A dictionary containing the pocket center and size.
        software (str): The path to the software to be used for rescoring.
        clustered_sdf (str): The path to the input SDF file containing the clustered poses.
        functions (List[str]): A list of the scoring functions to be used.
        ncpus (int): The number of CPUs to use for parallel execution.

    Returns:
        None
    """
    
    tic = time.perf_counter()
    rescoring_folder_name = Path(clustered_sdf).stem
    rescoring_folder = w_dir / f'rescoring_{rescoring_folder_name}'
    (rescoring_folder).mkdir(parents=True, exist_ok=True)

    def gnina_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Performs rescoring of ligand poses using the gnina software package. The function splits the input SDF file into
        smaller files, and then runs gnina on each of these files in parallel. The results are then combined into a single
        Pandas dataframe and saved to a CSV file.

        Args:
            sdf (str): The path to the input SDF file.
            ncpus (int): The number of CPUs to use for parallel execution.
            column_name (str): The name of the column in the output dataframe that will contain the rescoring results.

        Returns:
            A Pandas dataframe containing the rescoring results.
        """
    def gnina_rescoring(sdf : str, ncpus : int, column_name : str):
        tic = time.perf_counter()
        cnn = 'crossdock_default2018'
        split_files_folder = split_sdf(rescoring_folder / f'{column_name}_rescoring', sdf, ncpus)
        split_files_sdfs = [split_files_folder / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]

        global gnina_rescoring_splitted

        def gnina_rescoring_splitted(split_file, protein_file, pocket_definition):
            gnina_folder = rescoring_folder / f'{column_name}_rescoring'
            results = gnina_folder / f'{Path(split_file).stem}_{column_name}.sdf'
            gnina_cmd = (
                f'{software}/gnina'
                f' --receptor {protein_file}'
                f' --ligand {split_file}'
                f' --out {results}'
                f' --center_x {pocket_definition["center"][0]}'
                f' --center_y {pocket_definition["center"][1]}'
                f' --center_z {pocket_definition["center"][2]}'
                f' --size_x {pocket_definition["size"][0]}'
                f' --size_y {pocket_definition["size"][1]}'
                f' --size_z {pocket_definition["size"][2]}'
                ' --cpu 1'
                ' --score_only'
                f' --cnn {cnn} --no_gpu'
            )
            try:
                subprocess.call(gnina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
            except Exception as e:
                printlog(f'{column_name} rescoring failed: ' + e)
            return
        results = parallel_executor(gnina_rescoring_splitted, split_files_sdfs, ncpus, protein_file=protein_file, pocket_definition=pocket_definition)
        try:
            gnina_dataframes = [PandasTools.LoadSDF(str(rescoring_folder / f'{column_name}_rescoring' / file),  idName='Pose ID', molColName=None, includeFingerprints=False, embedProps=False, removeHs=False, strictParsing=True) for file in os.listdir(rescoring_folder / f'{column_name}_rescoring') if file.startswith('split') and file.endswith('.sdf')]
        except Exception as e:
            printlog(f'ERROR: Failed to Load {column_name} rescoring SDF file!')
            printlog(e)
        try:
            gnina_rescoring_results = pd.concat(gnina_dataframes)
        except Exception as e:
            printlog(f'ERROR: Could not combine {column_name} rescored poses')
            printlog(e)
        gnina_rescoring_results.rename(columns={'minimizedAffinity': 'GNINA_Affinity',
                                                'CNNscore': 'CNN-Score',
                                                'CNNaffinity': 'CNN-Affinity'},
                                                inplace=True)
        gnina_rescoring_results = gnina_rescoring_results[['Pose ID', column_name]]
        gnina_scores_path = rescoring_folder / f'{column_name}_rescoring' / f'{column_name}_scores.csv'
        gnina_rescoring_results.to_csv(gnina_scores_path, index=False)
        delete_files(rescoring_folder / f'{column_name}_rescoring', f'{column_name}_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with {column_name} complete in {toc - tic:0.4f}!')
        return gnina_rescoring_results

    def vinardo_rescoring(sdf: str, ncpus: int, column_name: str) -> DataFrame:
        """
        Performs rescoring of poses using the Vinardo scoring function.

        Args:
            sdf (str): The path to the input SDF file containing the poses to be rescored.
            ncpus (int): The number of CPUs to be used for the rescoring process.
            column_name (str): The name of the column in the output dataframe to store the Vinardo scores.

        Returns:
            DataFrame: A dataframe containing the 'Pose ID' and Vinardo score columns for the rescored poses.
        """
        tic = time.perf_counter()
        printlog('Rescoring with Vinardo')
        
        vinardo_rescoring_folder = rescoring_folder / 'Vinardo_rescoring'
        vinardo_rescoring_folder.mkdir(parents=True, exist_ok=True)
        results = vinardo_rescoring_folder / 'rescored_Vinardo.sdf'
        vinardo_cmd = (
            f"{software}/gnina"
            f" --receptor {protein_file}"
            f" --ligand {sdf}"
            f" --out {results}"
            f" --center_x {pocket_definition['center'][0]}"
            f" --center_y {pocket_definition['center'][1]}"
            f" --center_z {pocket_definition['center'][2]}"
            f" --size_x {pocket_definition['size'][0]}"
            f" --size_y {pocket_definition['size'][1]}"
            f" --size_z {pocket_definition['size'][2]}"
            " --score_only"
            " --scoring vinardo"
            " --cnn_scoring none"
        )
        subprocess.call(vinardo_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        vinardo_rescoring_results = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None,
                                                        includeFingerprints=False, removeHs=False)
        vinardo_rescoring_results.rename(columns={'minimizedAffinity': column_name}, inplace=True)
        vinardo_rescoring_results = vinardo_rescoring_results[['Pose ID', column_name]]
        vinardo_scores_path = vinardo_rescoring_folder / 'Vinardo_scores.csv'
        vinardo_rescoring_results.to_csv(vinardo_scores_path, index=False)
        delete_files(vinardo_rescoring_folder, 'Vinardo_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with Vinardo complete in {toc - tic:0.4f}!')
        return vinardo_rescoring_results

    def AD4_rescoring(sdf: str, ncpus: int, column_name: str) -> DataFrame:
        """
        Performs rescoring of poses using the AutoDock4 (AD4) scoring function.

        Args:
            sdf (str): The path to the input SDF file containing the poses to be rescored.
            ncpus (int): The number of CPUs to be used for the rescoring process.
            column_name (str): The name of the column in the output dataframe to store the AD4 scores.

        Returns:
            DataFrame: A dataframe containing the 'Pose ID' and AD4 score columns for the rescored poses.
        """
        tic = time.perf_counter()
        printlog('Rescoring with AD4')
    
        ad4_rescoring_folder = Path(rescoring_folder) / 'AD4_rescoring'
        ad4_rescoring_folder.mkdir(parents=True, exist_ok=True)
        results = ad4_rescoring_folder / 'rescored_AD4.sdf'
    
        AD4_cmd = (
            f"{software}/gnina"
            f" --receptor {protein_file}"
            f" --ligand {sdf}"
            f" --out {results}"
            f" --center_x {pocket_definition['center'][0]}"
            f" --center_y {pocket_definition['center'][1]}"
            f" --center_z {pocket_definition['center'][2]}"
            f" --size_x {pocket_definition['size'][0]}"
            f" --size_y {pocket_definition['size'][1]}"
            f" --size_z {pocket_definition['size'][2]}"
            " --score_only"
            " --scoring ad4_scoring"
            " --cnn_scoring none"
        )
    
        subprocess.run(AD4_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    
        AD4_rescoring_results = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        AD4_rescoring_results.rename(columns={'minimizedAffinity': column_name}, inplace=True)
        AD4_rescoring_results = AD4_rescoring_results[['Pose ID', column_name]]
    
        ad4_scores_file = ad4_rescoring_folder / 'AD4_scores.csv'
        AD4_rescoring_results.to_csv(ad4_scores_file, index=False)
    
        delete_files(ad4_rescoring_folder, 'AD4_scores.csv')
    
        toc = time.perf_counter()
        printlog(f'Rescoring with AD4 complete in {toc-tic:0.4f}!')
    
        return AD4_rescoring_results

    def rfscorevs_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores poses in an SDF file using RFScoreVS and returns the results as a pandas DataFrame.

        Args:
            sdf (str): Path to the SDF file containing the poses to be rescored.
            ncpus (int): Number of CPUs to use for the RFScoreVS calculation.
            column_name (str): Name of the column to be used for the RFScoreVS scores in the output DataFrame.

        Returns:
            pandas.DataFrame: DataFrame containing the RFScoreVS scores for each pose in the input SDF file.
        """
        tic = time.perf_counter()
        printlog('Rescoring with RFScoreVS')
        (rescoring_folder / 'RFScoreVS_rescoring').mkdir(parents=True, exist_ok=True)
        rfscorevs_cmd = f'{software}/rf-score-vs --receptor {protein_file} {str(sdf)} -O {rescoring_folder / "RFScoreVS_rescoring" / "RFScoreVS_scores.csv"} -n {ncpus}'
        subprocess.call(rfscorevs_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        rfscorevs_results = pd.read_csv(rescoring_folder / 'RFScoreVS_rescoring' / 'RFScoreVS_scores.csv', delimiter=',', header=0)
        rfscorevs_results = rfscorevs_results.rename(columns={'name': 'Pose ID', 'RFScoreVS_v2': column_name})
        rfscorevs_results.to_csv(rescoring_folder / 'RFScoreVS_rescoring' / 'RFScoreVS_scores.csv', index=False)
        delete_files(rescoring_folder / 'RFScoreVS_rescoring', 'RFScoreVS_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with RFScoreVS complete in {toc-tic:0.4f}!')
        return rfscorevs_results

    def plp_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores ligands using PLP scoring function.

        Args:
        sdf (str): Path to the input SDF file.
        ncpus (int): Number of CPUs to use for docking.
        column_name (str): Name of the column to store the PLP scores.

        Returns:
        pandas.DataFrame: DataFrame containing the Pose ID and PLP scores.
        """
        tic = time.perf_counter()
        printlog('Rescoring with PLP')
        plants_search_speed = 'speed1'
        ants = '20'
        plp_rescoring_folder = Path(rescoring_folder) / 'PLP_rescoring'
        plp_rescoring_folder.mkdir(parents=True, exist_ok=True)
        # Convert protein file to .mol2 using open babel
        plants_protein_mol2 = plp_rescoring_folder / 'protein.mol2'
        try:
            printlog('Converting protein file to .mol2 format for PLANTS docking...')
            obabel_command = 'obabel -ipdb ' + str(protein_file) + ' -O ' + str(plants_protein_mol2)
            subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('ERROR: Failed to convert protein file to .mol2!')
            printlog(e)
        # Convert clustered ligand file to .mol2 using open babel
        plants_ligands_mol2 = plp_rescoring_folder / 'ligands.mol2'
        try:
            obabel_command = f'obabel -isdf {str(sdf)} -O {plants_ligands_mol2}'
            os.system(obabel_command)
        except Exception as e:
            printlog('ERROR: Failed to convert clustered library file to .mol2!')
            printlog(e)
        # Generate plants config file
        plp_rescoring_config_path_txt = plp_rescoring_folder / 'config.txt'
        plp_config = ['# search algorithm\n',
                      'search_speed ' + plants_search_speed + '\n',
                      'aco_ants ' + ants + '\n',
                      'flip_amide_bonds 0\n',
                      'flip_planar_n 1\n',
                      'force_flipped_bonds_planarity 0\n',
                      'force_planar_bond_rotation 1\n',
                      'rescore_mode simplex\n',
                      'flip_ring_corners 0\n',
                      '# scoring functions\n',
                      '# Intermolecular (protein-ligand interaction scoring)\n',
                      'scoring_function plp\n',
                      'outside_binding_site_penalty 50.0\n',
                      'enable_sulphur_acceptors 1\n',
                      '# Intramolecular ligand scoring\n',
                      'ligand_intra_score clash2\n',
                      'chemplp_clash_include_14 1\n',
                      'chemplp_clash_include_HH 0\n',

                      '# input\n',
                      'protein_file ' + str(plants_protein_mol2) + '\n',
                      'ligand_file ' + str(plants_ligands_mol2) + '\n',

                      '# output\n',
                      'output_dir ' + str(plp_rescoring_folder / 'results') + '\n',

                      '# write single mol2 files (e.g. for RMSD calculation)\n',
                      'write_multi_mol2 1\n',

                      '# binding site definition\n',
                      'bindingsite_center ' + str(pocket_definition["center"][0]) + ' ' + str(pocket_definition["center"][1]) + ' ' + str(pocket_definition["center"][2]) + '\n',
                      'bindingsite_radius ' + str(pocket_definition["size"][0] / 2) + '\n',

                      '# cluster algorithm\n',
                      'cluster_structures 10\n',
                      'cluster_rmsd 2.0\n',

                      '# write\n',
                      'write_ranking_links 0\n',
                      'write_protein_bindingsite 1\n',
                      'write_protein_conformations 1\n',
                      'write_protein_splitted 1\n',
                      'write_merged_protein 0\n',
                      '####\n']
        plp_rescoring_config_path_config = plp_rescoring_config_path_txt.with_suffix('.config')
        with plp_rescoring_config_path_config.open('w') as configwriter:
            configwriter.writelines(plp_config)

        # Run PLANTS docking
        plp_rescoring_command = f'{software}/PLANTS --mode rescore {plp_rescoring_config_path_config}'
        subprocess.call(plp_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)

        # Fetch results
        results_csv_location = plp_rescoring_folder / 'results' / 'ranking.csv'
        plp_results = pd.read_csv(results_csv_location, sep=',', header=0)
        plp_results.rename(columns={'TOTAL_SCORE': column_name}, inplace=True)
        for i, row in plp_results.iterrows():
            split = row['LIGAND_ENTRY'].split('_')
            plp_results.loc[i, ['Pose ID']] = f'{split[0]}_{split[1]}_{split[2]}'
        plp_rescoring_output = plp_results[['Pose ID', column_name]]
        plp_rescoring_output.to_csv(rescoring_folder / 'PLP_rescoring' / 'PLP_scores.csv', index=False)

        # Remove files
        plants_ligands_mol2.unlink()
        delete_files(rescoring_folder / 'PLP_rescoring', 'PLP_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with PLP complete in {toc-tic:0.4f}!')
        return plp_rescoring_output

    def chemplp_rescoring(sdf : str, ncpus : int, column_name : str):
        tic = time.perf_counter()
        printlog('Rescoring with CHEMPLP')
        plants_search_speed = 'speed1'
        ants = '20'
        chemplp_rescoring_folder = rescoring_folder / 'CHEMPLP_rescoring'
        chemplp_rescoring_folder.mkdir(parents=True, exist_ok=True)
        # Convert protein file to .mol2 using open babel
        plants_protein_mol2 = chemplp_rescoring_folder / 'protein.mol2'
        try:
            printlog('Converting protein file to .mol2 format for PLANTS docking...')
            obabel_command = 'obabel -ipdb ' + \
                str(protein_file) + ' -O ' + str(plants_protein_mol2)
            subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('ERROR: Failed to convert protein file to .mol2!')
            printlog(e)
        # Convert clustered ligand file to .mol2 using open babel
        plants_ligands_mol2 = chemplp_rescoring_folder / 'ligands.mol2'
        try:
            obabel_command = f'obabel -isdf {str(sdf)} -O {plants_ligands_mol2}'
            os.system(obabel_command)
        except Exception as e:
            printlog('ERROR: Failed to convert clustered library file to .mol2!')
            printlog(e)
        chemplp_rescoring_config_path_txt = chemplp_rescoring_folder / 'config.txt'
        chemplp_config = ['# search algorithm\n',
                          'search_speed ' + plants_search_speed + '\n',
                          'aco_ants ' + ants + '\n',
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
                          'ligand_file ' + str(plants_ligands_mol2) + '\n',

                          '# output\n',
                          'output_dir ' + str(chemplp_rescoring_folder / 'results') + '\n',

                          '# write single mol2 files (e.g. for RMSD calculation)\n',
                          'write_multi_mol2 1\n',

                          '# binding site definition\n',
                          'bindingsite_center ' + str(pocket_definition["center"][0]) + ' ' + str(pocket_definition["center"][1]) + ' ' + str(pocket_definition["center"][2]) + '\n',
                          'bindingsite_radius ' + str(pocket_definition["size"][0] / 2) + '\n',

                          '# cluster algorithm\n',
                          'cluster_structures 10\n',
                          'cluster_rmsd 2.0\n',

                          '# write\n',
                          'write_ranking_links 0\n',
                          'write_protein_bindingsite 1\n',
                          'write_protein_conformations 1\n',
                          'write_protein_splitted 1\n',
                          'write_merged_protein 0\n',
                          '####\n']
        # Write config file
        chemplp_rescoring_config_path_config = chemplp_rescoring_config_path_txt.with_suffix(
            '.config')
        with chemplp_rescoring_config_path_config.open('w') as configwriter:
            configwriter.writelines(chemplp_config)

        # Run PLANTS docking
        chemplp_rescoring_command = f'{software}/PLANTS --mode rescore {chemplp_rescoring_config_path_config}'
        subprocess.call(chemplp_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)

        # Fetch results
        results_csv_location = chemplp_rescoring_folder / 'results' / 'ranking.csv'
        chemplp_results = pd.read_csv(results_csv_location, sep=',', header=0)
        chemplp_results.rename(columns={'TOTAL_SCORE': column_name}, inplace=True)
        for i, row in chemplp_results.iterrows():
            split = row['LIGAND_ENTRY'].split('_')
            chemplp_results.loc[i, ['Pose ID']] = f'{split[0]}_{split[1]}_{split[2]}'
        chemplp_rescoring_output = chemplp_results[['Pose ID', column_name]]
        chemplp_rescoring_output.to_csv(rescoring_folder / 'CHEMPLP_rescoring' / 'CHEMPLP_scores.csv', index=False)

        # Remove files
        plants_ligands_mol2.unlink()
        delete_files(rescoring_folder / 'CHEMPLP_rescoring', 'CHEMPLP_scores.csv')

        toc = time.perf_counter()
        printlog(f'Rescoring with CHEMPLP complete in {toc-tic:0.4f}!')
        return chemplp_rescoring_output

    def ECIF_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Performs rescoring with ECIF.

        Args:
        sdf (str): Path to the input SDF file.
        ncpus (int): Number of CPUs to use for parallel execution.
        column_name (str): Name of the column to store the ECIF scores.

        Returns:
        pandas.DataFrame: DataFrame containing the ECIF scores for each pose ID.
        """
        printlog('Rescoring with ECIF')
        ECIF_rescoring_folder = rescoring_folder / 'ECIF_rescoring'
        ECIF_rescoring_folder.mkdir(parents=True, exist_ok=True)
        split_dir = split_sdf_single(ECIF_rescoring_folder, sdf)
        ligands = [split_dir / x for x in os.listdir(split_dir) if x[-3:] == "sdf"]

        def ECIF_rescoring_single(ligand, protein_file):
            ECIF = GetECIF(protein_file, ligand, distance_cutoff=6.0)
            ligand_descriptors = GetRDKitDescriptors(ligand)
            all_descriptors_single = pd.DataFrame(ECIF, columns=PossibleECIF).join(pd.DataFrame(ligand_descriptors, columns=LigandDescriptors))
            return all_descriptors_single

        results = parallel_executor(ECIF_rescoring_single, ligands, ncpus, protein_file=protein_file)
        all_descriptors = pd.concat(results)

        model = pickle.load(open('software/ECIF6_LD_GBT.pkl', 'rb'))
        ids = PandasTools.LoadSDF(str(sdf), molColName=None, idName='Pose ID')
        ECIF_rescoring_results = pd.DataFrame(ids, columns=["Pose ID"]).join(pd.DataFrame(model.predict(all_descriptors), columns=[column_name]))
        ECIF_rescoring_results.to_csv(ECIF_rescoring_folder / 'ECIF_scores.csv', index=False)
        delete_files(ECIF_rescoring_folder, 'ECIF_scores.csv')
        return ECIF_rescoring_results

    def oddt_nnscore_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores the input SDF file using the NNscore algorithm and returns a Pandas dataframe with the rescored values.

        Args:
        sdf (str): Path to the input SDF file.
        ncpus (int): Number of CPUs to use for the rescoring.
        column_name (str): Name of the column to store the rescored values in the output dataframe.

        Returns:
        df (Pandas dataframe): Dataframe with the rescored values and the corresponding pose IDs.
        """
        tic = time.perf_counter()
        printlog('Rescoring with NNscore')
        nnscore_rescoring_folder = rescoring_folder / 'NNScore_rescoring'
        nnscore_rescoring_folder.mkdir(parents=True, exist_ok=True)
        pickle_path = f'{software}/models/NNScore_pdbbind2016.pickle'
        results = nnscore_rescoring_folder / 'rescored_NNscore.sdf'
        nnscore_rescoring_command = ('oddt_cli ' + str(sdf) + ' --receptor ' + str(protein_file) + ' -n ' + str(ncpus) + ' --score_file ' + str(pickle_path) + ' -O ' + str(results))
        subprocess.call(nnscore_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        df = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        df.rename(columns={'nnscore': column_name}, inplace=True)
        df = df[['Pose ID', column_name]]
        df.to_csv(nnscore_rescoring_folder / 'NNScore_scores.csv', index=False)
        toc = time.perf_counter()
        printlog(f'Rescoring with NNscore complete in {toc-tic:0.4f}!')
        delete_files(nnscore_rescoring_folder, 'NNScore_scores.csv')
        return df

    def oddt_plecscore_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores the input SDF file using the PLECscore rescoring method.

        Args:
        - sdf (str): the path to the input SDF file
        - ncpus (int): the number of CPUs to use for the rescoring calculation
        - column_name (str): the name of the column to use for the rescoring results

        Returns:
        - df (pandas.DataFrame): a DataFrame containing the rescoring results, with columns 'Pose ID' and 'column_name'
        """
        tic = time.perf_counter()
        printlog('Rescoring with PLECscore')
        plecscore_rescoring_folder = rescoring_folder / 'PLECScore_rescoring'
        plecscore_rescoring_folder.mkdir(parents=True, exist_ok=True)
        pickle_path = f'{software}/models/PLECnn_p5_l1_pdbbind2016_s65536.pickle'
        results = plecscore_rescoring_folder / 'rescored_PLECnn.sdf'
        plecscore_rescoring_command = ('oddt_cli ' + str(sdf) + ' --receptor ' + str(protein_file) + ' -n ' + str(ncpus) + ' --score_file ' + str(pickle_path) + ' -O ' + str(results)        )
        subprocess.call(plecscore_rescoring_command, shell=True)
        df = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        df.rename(columns={'PLECnn_p5_l1_s65536': column_name}, inplace=True)
        df = df[['Pose ID', column_name]]
        df.to_csv(plecscore_rescoring_folder / 'PLECScore_scores.csv', index=False)
        toc = time.perf_counter()
        printlog(f'Rescoring with PLECScore complete in {toc-tic:0.4f}!')
        delete_files(plecscore_rescoring_folder, 'PLECScore_scores.csv')
        return df

    def SCORCH_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores ligands in an SDF file using SCORCH and saves the results in a CSV file.

        Args:
            sdf (str): Path to the SDF file containing the ligands to be rescored.
            ncpus (int): Number of CPUs to use for parallel processing.
            column_name (str): Name of the column to store the SCORCH scores in the output CSV file.

        Returns:
            None
        """
        tic = time.perf_counter()
        SCORCH_rescoring_folder = rescoring_folder / 'SCORCH_rescoring'
        SCORCH_rescoring_folder.mkdir(parents=True, exist_ok=True)
        SCORCH_protein = SCORCH_rescoring_folder / "protein.pdbqt"
        printlog('Converting protein file to .pdbqt ...')
        obabel_command = f'obabel -ipdb {protein_file} -O {SCORCH_protein} --partialcharges gasteiger'
        subprocess.call(obabel_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        # Convert ligands to pdbqt
        sdf_file_name = sdf.stem
        printlog(f'Converting SDF file {sdf_file_name}.sdf to .pdbqt files...')
        split_files_folder = SCORCH_rescoring_folder / f'split_{sdf_file_name}'
        split_files_folder.mkdir(exist_ok=True)
        num_molecules = parallel_sdf_to_pdbqt(sdf, split_files_folder, ncpus)
        print(f"Converted {num_molecules} molecules.")
        # Run SCORCH
        printlog('Rescoring with SCORCH')
        SCORCH_command = f'python {software}/SCORCH/scorch.py --receptor {SCORCH_protein} --ligand {split_files_folder} --out {SCORCH_rescoring_folder}/scoring_results.csv --threads {ncpus} --return_pose_scores'
        subprocess.call(SCORCH_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        # Clean data
        SCORCH_scores = pd.read_csv(SCORCH_rescoring_folder / 'scoring_results.csv')
        SCORCH_scores = SCORCH_scores.rename(columns={'Ligand_ID': 'Pose ID',
                                                      'SCORCH_pose_score': column_name})
        SCORCH_scores = SCORCH_scores[[column_name, 'Pose ID']]
        SCORCH_scores.to_csv(SCORCH_rescoring_folder / 'SCORCH_scores.csv', index=False)
        delete_files(SCORCH_rescoring_folder, 'SCORCH_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with SCORCH complete in {toc-tic:0.4f}!')
        return

    def RTMScore_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores poses in an SDF file using RTMScore.

        Args:
        - sdf (str): Path to the SDF file containing the poses to be rescored.
        - ncpus (int): Number of CPUs to use for parallel execution.
        - column_name (str): Name of the column in the output CSV file that will contain the RTMScore scores.

        Returns:
        - None
        """
        tic = time.perf_counter()
        (rescoring_folder / 'RTMScore_rescoring').mkdir(parents=True, exist_ok=True)
        RTMScore_pocket = str(protein_file).replace('.pdb', '_pocket.pdb')
        printlog('Rescoring with RTMScore')
        split_files_folder = split_sdf(rescoring_folder / 'RTMScore_rescoring', sdf, ncpus * 5)
        split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
        global RTMScore_rescoring_splitted
        
        def RTMScore_rescoring_splitted(split_file, protein_file):
            output_file = str(rescoring_folder / 'RTMScore_rescoring' / f'{split_file.stem}_RTMScore.csv')
            try:
                rtmscore(prot=RTMScore_pocket, lig=split_file, output=output_file, model=str(f'{software}/RTMScore/trained_models/rtmscore_model1.pth'), ncpus=1)
            except BaseException:
                printlog('RTMScore scoring with pocket failed, scoring with whole protein...')
                rtmscore(prot=protein_file, lig=split_file, output=output_file, model=str(f'{software}/RTMScore/trained_models/rtmscore_model1.pth'), ncpus=1)
            
        res = parallel_executor(RTMScore_rescoring_splitted, split_files_sdfs, ncpus, protein_file=protein_file)
        
        results_dataframes = [pd.read_csv(file) for file in glob.glob(str(rescoring_folder / 'RTMScore_rescoring' / 'split*.csv'))]
        results = pd.concat(results_dataframes)
        results['Pose ID'] = results['Pose ID'].apply(lambda x: x.split('-')[0])
        results.to_csv(rescoring_folder / 'RTMScore_rescoring' / 'RTMScore_scores.csv', index=False)
        delete_files(rescoring_folder / 'RTMScore_rescoring', 'RTMScore_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with RTMScore complete in {toc-tic:0.4f}!')
        return

    def LinF9_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Performs rescoring of poses in an SDF file using the LinF9 scoring function.

        Args:
        sdf (str): The path to the SDF file containing the poses to be rescored.
        ncpus (int): The number of CPUs to use for parallel execution.
        column_name (str): The name of the column to store the rescoring results.

        Returns:
        pandas.DataFrame: A DataFrame containing the rescoring results, with columns 'Pose ID' and the specified column name.
        """
        tic = time.perf_counter()
        (rescoring_folder / 'LinF9_rescoring').mkdir(parents=True, exist_ok=True)
        split_files_folder = split_sdf(rescoring_folder / 'LinF9_rescoring', sdf, ncpus)
        split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
        
        global LinF9_rescoring_splitted

        def LinF9_rescoring_splitted(split_file, protein_file, pocket_definition):
            LinF9_folder = rescoring_folder / 'LinF9_rescoring'
            results = LinF9_folder / f'{split_file.stem}_LinF9.sdf'
            LinF9_cmd = (
                f'{software}/smina.static' +
                f' --receptor {protein_file}' +
                f' --ligand {split_file}' +
                f' --out {results}' +
                f' --center_x {pocket_definition["center"][0]}' +
                f' --center_y {pocket_definition["center"][1]}' +
                f' --center_z {pocket_definition["center"][2]}' +
                f' --size_x {pocket_definition["size"][0]}' +
                f' --size_y {pocket_definition["size"][1]}' +
                f' --size_z {pocket_definition["size"][2]}' +
                ' --cpu 1' +
                ' --scoring Lin_F9 --score_only'
            )
            try:
                subprocess.call(LinF9_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
            except Exception as e:
                printlog(f'LinF9 rescoring failed: {e}')
            return

        res = parallel_executor(LinF9_rescoring_splitted, split_files_sdfs, ncpus, protein_file=protein_file, pocket_definition=pocket_definition)
        
        try:
            LinF9_dataframes = [PandasTools.LoadSDF(str(rescoring_folder / 'LinF9_rescoring' / file),
                                                    idName='Pose ID',
                                                    molColName=None,
                                                    includeFingerprints=False,
                                                    embedProps=False,
                                                    removeHs=False,
                                                    strictParsing=True) for file in os.listdir(
                                                    rescoring_folder /
                                                    'LinF9_rescoring') if file.startswith('split') and file.endswith('.sdf')
                                ]
        except Exception as e:
            printlog('ERROR: Failed to Load LinF9 rescoring SDF file!')
            printlog(e)

        try:
            LinF9_rescoring_results = pd.concat(LinF9_dataframes)
        except Exception as e:
            printlog('ERROR: Could not combine LinF9 rescored poses')
            printlog(e)

        LinF9_rescoring_results.rename(columns={'minimizedAffinity': column_name},inplace=True)
        LinF9_rescoring_results = LinF9_rescoring_results[['Pose ID', column_name]]
        LinF9_rescoring_results.to_csv(rescoring_folder / 'LinF9_rescoring' / 'LinF9_scores.csv', index=False)
        delete_files(rescoring_folder / 'LinF9_rescoring', 'LinF9_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with LinF9 complete in {toc-tic:0.4f}!')
        return LinF9_rescoring_results

    def AAScore_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores poses in an SDF file using the AA-Score tool.

        Args:
        sdf (str): The path to the SDF file containing the poses to be rescored.
        ncpus (int): The number of CPUs to use for parallel processing.
        column_name (str): The name of the column to be used for the rescored scores.

        Returns:
        A pandas DataFrame containing the rescored poses and their scores.
        """
        tic = time.perf_counter()
        (rescoring_folder / 'AAScore_rescoring').mkdir(parents=True, exist_ok=True)
        pocket = str(protein_file).replace('.pdb', '_pocket.pdb')

        if ncpus == 1:
            printlog('Rescoring with AAScore')
            results = rescoring_folder / 'AAScore_rescoring' / 'rescored_AAScore.csv'
            AAscore_cmd = f'python {software}/AA-Score-Tool-main/AA_Score.py --Rec {pocket} --Lig {sdf} --Out {results}'
            subprocess.call(AAscore_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
            AAScore_rescoring_results = pd.read_csv(results, delimiter='\t', header=None, names=['Pose ID', column_name])
        else:
            split_files_folder = split_sdf(rescoring_folder / 'AAScore_rescoring', sdf, ncpus)
            split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
            global AAScore_rescoring_splitted

            def AAScore_rescoring_splitted(split_file):
                AAScore_folder = rescoring_folder / 'AAScore_rescoring'
                results = AAScore_folder / f'{split_file.stem}_AAScore.csv'
                AAScore_cmd = f'python {software}/AA-Score-Tool-main/AA_Score.py --Rec {pocket} --Lig {split_file} --Out {results}'
                try:
                    subprocess.call( AAScore_cmd,shell=True,stdout=DEVNULL,stderr=STDOUT)
                except Exception as e:
                    printlog('AAScore rescoring failed: ' + str(e))

            res = parallel_executor(AAScore_rescoring_splitted, split_files_sdfs, ncpus)
        
            try:
                AAScore_dataframes = [pd.read_csv(rescoring_folder / 'AAScore_rescoring' / file,
                                                    delimiter='\t',
                                                    header=None,
                                                    names=['Pose ID', column_name]) 
                                    for file in os.listdir(rescoring_folder / 'AAScore_rescoring') if file.startswith('split') and file.endswith('.csv')
                                    ]
            except Exception as e:
                printlog('ERROR: Failed to Load AAScore rescoring SDF file!')
                printlog(e)
            else:
                try:
                    AAScore_rescoring_results = pd.concat(AAScore_dataframes)
                except Exception as e:
                    printlog('ERROR: Could not combine AAScore rescored poses')
                    printlog(e)
                else:
                    delete_files(rescoring_folder / 'AAScore_rescoring', 'AAScore_scores.csv')
            AAScore_rescoring_results.to_csv(rescoring_folder / 'AAScore_rescoring' / 'AAScore_scores.csv', index=False)
            toc = time.perf_counter()
            printlog(f'Rescoring with AAScore complete in {toc-tic:0.4f}!')
            return AAScore_rescoring_results

    def KORPL_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores a given SDF file using KORP-PL software and saves the results to a CSV file.

        Args:
        - sdf (str): The path to the SDF file to be rescored.
        - ncpus (int): The number of CPUs to use for parallel processing.
        - column_name (str): The name of the column to store the rescored values in.

        Returns:
        - None
        """
        tic = time.perf_counter()
        (rescoring_folder / 'KORPL_rescoring').mkdir(parents=True, exist_ok=True)
        split_files_folder = split_sdf((rescoring_folder / 'KORPL_rescoring'), sdf, ncpus)
        split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
        global KORPL_rescoring_splitted

        def KORPL_rescoring_splitted(split_file, protein_file):
            df = PandasTools.LoadSDF(str(split_file), idName='Pose ID', molColName=None)
            df = df[['Pose ID']]
            korpl_command = (f'{software}/KORP-PL' +
                            ' --receptor ' + str(protein_file) +
                            ' --ligand ' + str(split_file) +
                            ' --sdf')
            process = subprocess.Popen(korpl_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            stdout, stderr = process.communicate()
            energies = []
            output = stdout.decode().splitlines()
            for line in output:
                if line.startswith('model'):
                    parts = line.split(',')
                    energy = round(float(parts[1].split('=')[1]), 2)
                    energies.append(energy)
            df[column_name] = energies
            output_csv = str(rescoring_folder / 'KORPL_rescoring' / (str(split_file.stem) + '_scores.csv'))
            df.to_csv(output_csv, index=False)
            return
            
        res = parallel_executor(KORPL_rescoring_splitted, split_files_sdfs, ncpus, protein_file=protein_file)
        
        print('Combining KORPL scores')
        scores_folder = rescoring_folder / 'KORPL_rescoring'
        # Get a list of all files with names ending in "_scores.csv"
        score_files = list(scores_folder.glob('*_scores.csv'))
        if not score_files:
            print("No CSV files found with names ending in '_scores.csv' in the specified folder.")
        else:
            # Read and concatenate the CSV files into a single DataFrame
            combined_scores_df = pd.concat([pd.read_csv(file) for file in score_files], ignore_index=True)
            # Save the combined scores to a single CSV file
            combined_scores_csv = scores_folder / 'KORPL_scores.csv'
            combined_scores_df.to_csv(combined_scores_csv, index=False)
        delete_files(rescoring_folder / 'KORPL_rescoring', 'KORPL_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with KORPL complete in {toc-tic:0.4f}!')
        return

    def ConvexPLR_rescoring(sdf : str, ncpus : int, column_name : str):
        """
        Rescores the given SDF file using Convex-PLR software and saves the results in a CSV file.

        Args:
        - sdf (str): path to the input SDF file
        - ncpus (int): number of CPUs to use for parallel processing
        - column_name (str): name of the column to store the scores in the output CSV file

        Returns:
        - None
        """
        tic = time.perf_counter()
        (rescoring_folder / 'ConvexPLR_rescoring').mkdir(parents=True, exist_ok=True)
        split_files_folder = split_sdf((rescoring_folder / 'ConvexPLR_rescoring'), sdf, ncpus)
        split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
        global ConvexPLR_rescoring_splitted

        def ConvexPLR_rescoring_splitted(split_file, protein_file):
            df = PandasTools.LoadSDF(str(split_file), idName='Pose ID', molColName=None)
            df = df[['Pose ID']]
            ConvexPLR_command = (
            'software/Convex-PL' +
            ' --receptor ' + str(protein_file) +
            ' --ligand ' + str(split_file) +
            ' --sdf --regscore')
            process = subprocess.Popen(ConvexPLR_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            stdout, stderr = process.communicate()
            energies = []
            output = stdout.decode().splitlines()
            for line in output:
                if line.startswith('model'):
                    parts = line.split(',')
                    energy = round(float(parts[1].split('=')[1]), 2)
                    energies.append(energy)
            df[column_name] = energies
            output_csv = str(rescoring_folder / 'ConvexPLR_rescoring' / (str(split_file.stem) + '_scores.csv'))
            df.to_csv(output_csv, index=False)
            return
        
        res = parallel_executor(ConvexPLR_rescoring_splitted, split_files_sdfs, ncpus, protein_file=protein_file)
        
        # Get a list of all files with names ending in "_scores.csv"
        score_files = list((rescoring_folder / 'ConvexPLR_rescoring').glob('*_scores.csv'))
        # Read and concatenate the CSV files into a single DataFrame
        combined_scores_df = pd.concat([pd.read_csv(file) for file in score_files], ignore_index=True)
        # Save the combined scores to a single CSV file
        combined_scores_csv = rescoring_folder / 'ConvexPLR_rescoring' / 'ConvexPLR_scores.csv'
        combined_scores_df.to_csv(combined_scores_csv, index=False)
        delete_files(rescoring_folder / 'ConvexPLR_rescoring', 'ConvexPLR_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with ConvexPLR complete in {toc-tic:0.4f}!')
        return

    rescoring_functions = {
    'GNINA_Affinity': (gnina_rescoring, 'GNINA_Affinity'),
    'CNN-Score': (gnina_rescoring, 'CNN-Score'),
    'CNN-Affinity': (gnina_rescoring, 'CNN-Affinity'),
    'Vinardo': (vinardo_rescoring, 'Vinardo'),
    'AD4': (AD4_rescoring, 'AD4'),
    'RFScoreVS': (rfscorevs_rescoring, 'RFScoreVS'),
    'PLP': (plp_rescoring, 'PLP'),
    'CHEMPLP': (chemplp_rescoring, 'CHEMPLP'),
    'NNScore': (oddt_nnscore_rescoring, 'NNScore'),
    'PLECnn': (oddt_plecscore_rescoring, 'PLECnn'),
    'LinF9': (LinF9_rescoring, 'LinF9'),
    'AAScore': (AAScore_rescoring, 'AAScore'),
    'ECIF': (ECIF_rescoring, 'ECIF'),
    'SCORCH': (SCORCH_rescoring, 'SCORCH'),
    'RTMScore': (RTMScore_rescoring, 'RTMScore'),
    'KORPL': (KORPL_rescoring, 'KORPL'),
    'ConvexPLR': (ConvexPLR_rescoring, 'ConvexPLR')
    #add new scoring functions here!
    }

    skipped_functions = []
    for function in functions:
        if not (rescoring_folder / f'{function}_rescoring' / f'{function}_scores.csv').is_file():
            rescoring_functions[function][0](clustered_sdf, ncpus, rescoring_functions[function][1])
        else:
            skipped_functions.append(function)
    if skipped_functions:
        printlog(f'Skipping functions: {", ".join(skipped_functions)}')


    score_files = [f'{function}_scores.csv' for function in functions]
    printlog(f'Combining all scores for {rescoring_folder}')
    csv_files = [file for file in (rescoring_folder.rglob('*.csv')) if file.name in score_files]
    csv_dfs = []
    for file in csv_files:
        df = pd.read_csv(file)
        if 'Unnamed: 0' in df.columns:
            df = df.drop(columns=['Unnamed: 0'])
        csv_dfs.append(df)
    combined_dfs = csv_dfs[0]
    for df in tqdm(csv_dfs[1:], desc='Combining scores', unit='files'):
        combined_dfs = pd.merge(combined_dfs, df, on='Pose ID', how='inner')
    first_column = combined_dfs.pop('Pose ID')
    combined_dfs.insert(0, 'Pose ID', first_column)
    columns = combined_dfs.columns
    col = columns[1:]
    for c in col.tolist():
        if c == 'Pose ID':
            pass
        if combined_dfs[c].dtypes is not float:
            combined_dfs[c] = combined_dfs[c].apply(pd.to_numeric, errors='coerce')
        else:
            pass
    combined_dfs.to_csv(rescoring_folder / 'allposes_rescored.csv', index=False)

    toc = time.perf_counter()
    printlog(f'Rescoring complete in {toc - tic:0.4f}!')
    return
