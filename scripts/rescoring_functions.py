import os
import shutil
import subprocess
import json
from subprocess import DEVNULL, STDOUT, PIPE
import pandas as pd
import functools
from rdkit import Chem
from rdkit.Chem import PandasTools
import oddt
from oddt.scoring.functions.NNScore import nnscore
from oddt.scoring.functions.RFScore import rfscore
from oddt.scoring.functions.PLECscore import PLECscore
from tqdm import tqdm
import multiprocessing
import concurrent.futures
import time
from scripts.utilities import *
from software.ECIF.ecif import *
# from software.SCORCH.scorch import parse_module_args, scoring
from IPython.display import display
import pickle
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from software.RTMScore.rtmscore_modified import *
from pathlib import Path
import glob

# TODO: add new scoring functions:
# _SIEVE_Score (no documentation)
# _AEScore


def delete_files(folder_path, save_file):
    folder = Path(folder_path)
    for item in folder.iterdir():
        if item.is_file() and item.name != save_file:
            item.unlink()
        elif item.is_dir():
            delete_files(item, save_file)
            if not any(item.iterdir()) and item.name != save_file:
                item.rmdir()

def parallel_executor(function, split_files_sdfs, ncpus, **kwargs):
    with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
                jobs = []
                for split_file in split_files_sdfs:
                    try:
                        job = executor.submit(function, split_file, **kwargs)
                        jobs.append(job)
                    except Exception as e:
                        printlog("Error in concurrent futures job creation: " + str(e))
                for job in tqdm(concurrent.futures.as_completed(jobs), total=len(split_files_sdfs), desc=f'Rescoring with {function}', unit='file'):
                    try:
                        res = job.result()
                    except Exception as e:
                        printlog("Error in concurrent futures job run: " + str(e))
    return res


def rescore_all( w_dir, protein_file, pocket_definition, software, clustered_sdf, functions, ncpus):
    tic = time.perf_counter()
    rescoring_folder_name = Path(clustered_sdf).stem
    rescoring_folder = w_dir / 'temp' / f'rescoring_{rescoring_folder_name}'
    (rescoring_folder).mkdir(parents=True, exist_ok=True)

    def gnina_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        (rescoring_folder / 'gnina_rescoring').mkdir(parents=True, exist_ok=True)
        cnn = 'crossdock_default2018'
        split_files_folder = split_sdf(rescoring_folder / 'gnina_rescoring', sdf, ncpus)
        split_files_sdfs = [split_files_folder / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]

        global gnina_rescoring_splitted

        def gnina_rescoring_splitted(split_file, protein_file, pocket_definition):
            gnina_folder = rescoring_folder / 'gnina_rescoring'
            results = gnina_folder / f'{Path(split_file).stem}_gnina.sdf'
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
                printlog('GNINA rescoring failed: ' + e)
            return
        results = parallel_executor(gnina_rescoring_splitted, split_files_sdfs, ncpus, protein_file=protein_file, pocket_definition=pocket_definition)
        try:
            gnina_dataframes = [PandasTools.LoadSDF(str(rescoring_folder / 'gnina_rescoring' / file),  idName='Pose ID', molColName=None, includeFingerprints=False, embedProps=False, removeHs=False, strictParsing=True) for file in os.listdir( rescoring_folder / 'gnina_rescoring') if file.startswith('split') and file.endswith('.sdf')]
        except Exception as e:
            printlog('ERROR: Failed to Load GNINA rescoring SDF file!')
            printlog(e)
        try:
            gnina_rescoring_results = pd.concat(gnina_dataframes)
        except Exception as e:
            printlog('ERROR: Could not combine GNINA rescored poses')
            printlog(e)
        gnina_rescoring_results.rename(columns={'minimizedAffinity': 'GNINA_Affinity',
                                                'CNNscore': 'CNN-Score',
                                                'CNNaffinity': 'CNN-Affinity'},
                                                inplace=True)
        gnina_rescoring_results = gnina_rescoring_results[['Pose ID', kwargs.get(column_name)]]
        gnina_rescoring_results.to_csv(rescoring_folder / 'gnina_rescoring' / f'{kwargs.get(column_name)}_scores.csv', index=False)
        delete_files(rescoring_folder / 'gnina_rescoring', f'{kwargs.get(column_name)}_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with GNINA complete in {toc - tic:0.4f}!')
        return gnina_rescoring_results

    def vinardo_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with Vinardo')
        (rescoring_folder / 'vinardo_rescoring').mkdir(parents=True, exist_ok=True)
        results = rescoring_folder / 'vinardo_rescoring' / 'rescored_vinardo.sdf'
        vinardo_cmd = (
            f"{software}/gnina" +
            f" --receptor {protein_file}" +
            f" --ligand {sdf}" +
            f" --out {results}" +
            f" --center_x {pocket_definition['center'][0]}" +
            f" --center_y {pocket_definition['center'][1]}" +
            f" --center_z {pocket_definition['center'][2]}" +
            f" --size_x {pocket_definition['size'][0]}" +
            f" --size_y {pocket_definition['size'][1]}" +
            f" --size_z {pocket_definition['size'][2]}" +
            " --score_only --scoring vinardo --cnn_scoring none"
        )
        subprocess.call(vinardo_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        vinardo_rescoring_results = PandasTools.LoadSDF( str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        vinardo_rescoring_results.rename(columns={'minimizedAffinity': kwargs.get(column_name)},inplace=True)
        vinardo_rescoring_results = vinardo_rescoring_results[['Pose ID', kwargs.get(column_name)]]
        vinardo_rescoring_results.to_csv(rescoring_folder / 'vinardo_rescoring' / 'vinardo_scores.csv', index=False)
        delete_files(rescoring_folder / 'vinardo_rescoring', 'vinardo_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with Vinardo complete in {toc - tic:0.4f}!')
        return vinardo_rescoring_results

    def AD4_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with AD4')
        rescoring_folder / 'AD4_rescoring'.mkdir(parents=True, exist_ok=True)
        results = rescoring_folder / 'AD4_rescoring' / 'rescored_AD4.sdf'
        AD4_cmd = (
            f"{software}/gnina" +
            f" --receptor {protein_file}" +
            f" --ligand {sdf}" +
            f" --out {results}" +
            f" --center_x {pocket_definition['center'][0]}" +
            f" --center_y {pocket_definition['center'][1]}" +
            f" --center_z {pocket_definition['center'][2]}" +
            f" --size_x {pocket_definition['size'][0]}" +
            f" --size_y {pocket_definition['size'][1]}" +
            f" --size_z {pocket_definition['size'][2]}" +
            " --score_only --scoring ad4_scoring --cnn_scoring none"
        )
        subprocess.call(AD4_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        AD4_rescoring_results = PandasTools.LoadSDF( str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        AD4_rescoring_results.rename(columns={'minimizedAffinity': kwargs.get(column_name)}, inplace=True)
        AD4_rescoring_results = AD4_rescoring_results[['Pose ID', kwargs.get(column_name)]]
        AD4_rescoring_results.to_csv(rescoring_folder / 'AD4_rescoring' / 'AD4_scores.csv', index=False)
        delete_files(rescoring_folder / 'AD4_rescoring', 'AD4_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with AD4 complete in {toc-tic:0.4f}!')
        return AD4_rescoring_results

    def rfscore_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with RFScoreVS')
        Path(rescoring_folder) / 'rfscorevs_rescoring'.mkdir(parents=True, exist_ok=True)
        results_path = Path(rescoring_folder) / 'rfscorevs_rescoring' / 'rfscorevs_scores.csv'
        if ncpus > 1:
            rfscore_cmd = f'{software}/rf-score-vs --receptor {protein_file} {str(sdf)} -O {results_path} -n {ncpus}'
        else:
            rfscore_cmd = f'{software}/rf-score-vs --receptor {protein_file} {str(sdf)} -O {results_path} -n 1'
        subprocess.call(rfscore_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        rfscore_results = pd.read_csv(results_path, delimiter=',', header=0)
        rfscore_results = rfscore_results.rename(columns={'name': 'Pose ID', 'RFScoreVS_v2': kwargs.get(column_name)}, inplace=True)
        rfscore_results.to_csv(Path(rescoring_folder) / 'rfscorevs_rescoring' / 'rfscorevs_scores.csv', index=False)
        delete_files(Path(rescoring_folder) / 'rfscorevs_rescoring', 'rfscorevs_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with RFScoreVS complete in {toc-tic:0.4f}!')
        return rfscore_results

    def plp_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with PLP')
        plants_search_speed = 'speed1'
        ants = '20'
        plp_rescoring_folder = Path(rescoring_folder) / 'plp_rescoring'
        Path(rescoring_folder) / 'plp_rescoring'.mkdir(parents=True, exist_ok=True)
        # Convert protein file to .mol2 using open babel
        plants_protein_mol2 = Path(rescoring_folder) / 'plp_rescoring' / 'protein.mol2'
        try:
            printlog('Converting protein file to .mol2 format for PLANTS docking...')
            obabel_command = 'obabel -ipdb ' + str(protein_file) + ' -O ' + str(plants_protein_mol2)
            subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('ERROR: Failed to convert protein file to .mol2!')
            printlog(e)
        # Convert clustered ligand file to .mol2 using open babel
        plants_ligands_mol2 = Path(rescoring_folder) / 'plp_rescoring' / 'ligands.mol2'
        try:
            obabel_command = f'obabel -isdf {str(sdf)} -O {plants_ligands_mol2}'
            os.system(obabel_command)
        except Exception as e:
            printlog('ERROR: Failed to convert clustered library file to .mol2!')
            printlog(e)
        # Generate plants config file
        plp_rescoring_config_path_txt = Path(rescoring_folder) / 'plp_rescoring' / 'config.txt'
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
                      'output_dir ' + str(Path(rescoring_folder) / 'plp_rescoring' / 'results') + '\n',

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
        results_csv_location = Path(rescoring_folder) / 'plp_rescoring' / 'results' / 'ranking.csv'
        plp_results = pd.read_csv(results_csv_location, sep=',', header=0)
        plp_results.rename(columns={'TOTAL_SCORE': kwargs.get(column_name)}, inplace=True)
        for i, row in plp_results.iterrows():
            split = row['LIGAND_ENTRY'].split('_')
            plp_results.loc[i, ['Pose ID']] = f'{split[0]}_{split[1]}_{split[2]}'
        plp_rescoring_output = plp_results[['Pose ID', kwargs.get(column_name)]]
        plp_rescoring_output.to_csv(rescoring_folder / 'plp_rescoring' / 'plp_scores.csv', index=False)

        # Remove files
        plants_ligands_mol2.unlink()
        delete_files(rescoring_folder / 'plp_rescoring', 'plp_scores.csv')

        toc = time.perf_counter()
        printlog(f'Rescoring with PLP complete in {toc-tic:0.4f}!')
        return plp_rescoring_output

    def chemplp_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with CHEMPLP')
        plants_search_speed = 'speed1'
        ants = '20'
        rescoring_folder / 'chemplp_rescoring'.mkdir(parents=True, exist_ok=True)
        # Convert protein file to .mol2 using open babel
        plants_protein_mol2 = rescoring_folder / 'chemplp_rescoring' / 'protein.mol2'
        try:
            printlog('Converting protein file to .mol2 format for PLANTS docking...')
            obabel_command = 'obabel -ipdb ' + str(protein_file) + ' -O ' + str(plants_protein_mol2)
            subprocess.call(obabel_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        except Exception as e:
            printlog('ERROR: Failed to convert protein file to .mol2!')
            printlog(e)
        # Convert clustered ligand file to .mol2 using open babel
        plants_ligands_mol2 = rescoring_folder / 'chemplp_rescoring' / 'ligands.mol2'
        try:
            obabel_command = f'obabel -isdf {str(sdf)} -O {plants_ligands_mol2}'
            os.system(obabel_command)
        except Exception as e:
            printlog('ERROR: Failed to convert clustered library file to .mol2!')
            printlog(e)
        chemplp_rescoring_config_path_txt = rescoring_folder / 'chemplp_rescoring' / 'config.txt'
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
                          'output_dir ' + str(rescoring_folder / 'chemplp_rescoring' / 'results') + '\n',

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
        chemplp_rescoring_config_path_config = chemplp_rescoring_config_path_txt.with_suffix('.config')
        with chemplp_rescoring_config_path_config.open('w') as configwriter:
            configwriter.writelines(chemplp_config)

        # Run PLANTS docking
        chemplp_rescoring_command = f'{software}/PLANTS --mode rescore {chemplp_rescoring_config_path_config}'
        subprocess.call(chemplp_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)

        # Fetch results
        results_csv_location = rescoring_folder / 'chemplp_rescoring' / 'results' / 'ranking.csv'
        chemplp_results = pd.read_csv(results_csv_location, sep=',', header=0)
        chemplp_results.rename(columns={'TOTAL_SCORE': kwargs.get(column_name)}, inplace=True)
        for i, row in chemplp_results.iterrows():
            split = row['LIGAND_ENTRY'].split('_')
            chemplp_results.loc[i, ['Pose ID']] = f'{split[0]}_{split[1]}_{split[2]}'
        chemplp_rescoring_output = chemplp_results[['Pose ID', kwargs.get(column_name)]]
        chemplp_rescoring_output.to_csv(rescoring_folder / 'chemplp_rescoring' / 'chemplp_scores.csv', index=False)

        # Remove files
        plants_ligands_mol2.unlink()
        delete_files(rescoring_folder / 'chemplp_rescoring', 'chemplp_scores.csv')

        toc = time.perf_counter()
        printlog(f'Rescoring with CHEMPLP complete in {toc-tic:0.4f}!')
        return chemplp_rescoring_output

    def ECIF_rescoring(sdf, ncpus, **kwargs):
        printlog('Rescoring with ECIF')
        rescoring_folder / 'ECIF_rescoring'.mkdir(parents=True, exist_ok=True)
        split_dir = split_sdf_single(rescoring_folder / 'ECIF_rescoring', sdf)
        ligands = [split_dir / x for x in os.listdir(split_dir) if x[-3:] == "sdf"]
        if ncpus == 1:
            ECIF = [GetECIF(protein_file, ligand, distance_cutoff=6.0)
                    for ligand in ligands]
            ligand_descriptors = [GetRDKitDescriptors(x) for x in ligands]
            all_descriptors = pd.DataFrame(ECIF, columns=PossibleECIF).join(pd.DataFrame(ligand_descriptors, columns=LigandDescriptors))
        else:
            def ECIF_rescoring_single(ligand, protein_file):
                ECIF = GetECIF(protein_file, ligand, distance_cutoff=6.0)
                ligand_descriptors = GetRDKitDescriptors(ligand)
                all_descriptors_single = pd.DataFrame(ECIF, columns=PossibleECIF).join(pd.DataFrame(ligand_descriptors, columns=LigandDescriptors))
                return all_descriptors_single

        all_descriptors = pd.DataFrame()
        results = parallel_executor(gnina_rescoring_splitted, ligands, ncpus, protein_file=protein_file, ligand=ligand)
        all_descriptors = pd.concat([all_descriptors, results])
        model = pickle.load(open('software/ECIF6_LD_GBT.pkl', 'rb'))
        ids = PandasTools.LoadSDF(str(sdf), molColName=None, idName='Pose ID')
        ECIF_rescoring_results = pd.DataFrame(ids, columns=["Pose ID"]).join(pd.DataFrame(model.predict(all_descriptors), columns=[kwargs.get(column_name)]))
        ECIF_rescoring_results.to_csv(rescoring_folder / 'ECIF_rescoring' / 'ECIF_scores.csv', index=False)
        delete_files(rescoring_folder / 'ECIF_rescoring', 'ECIF_scores.csv')
        return ECIF_rescoring_results

    def oddt_nnscore_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with NNscore')
        rescoring_folder / 'nnscore_rescoring'.mkdir(parents=True, exist_ok=True)
        pickle_path = f'{software}/models/NNScore_pdbbind2016.pickle'
        results = rescoring_folder / 'nnscore_rescoring' / 'rescored_NNscore.sdf'
        nnscore_rescoring_command = ('oddt_cli ' + str(sdf) +
                                     ' --receptor ' + str(protein_file) +
                                     ' -n ' + str(ncpus) +
                                     ' --score_file ' + str(pickle_path) +
                                     ' -O ' + str(results))
        subprocess.call(nnscore_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        df = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        df.rename(columns={'nnscore': kwargs.get(column_name)}, inplace=True)
        df = df[['Pose ID', kwargs.get(column_name)]]
        df.to_csv(rescoring_folder / 'nnscore_rescoring' / 'nnscore_scores.csv', index=False)
        toc = time.perf_counter()
        printlog(f'Rescoring with NNscore complete in {toc-tic:0.4f}!')
        delete_files(rescoring_folder / 'nnscore_rescoring', 'nnscore_scores.csv')
        return df

    def oddt_plecscore_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        printlog('Rescoring with PLECscore')
        rescoring_folder / 'plecscore_rescoring'.mkdir(parents=True, exist_ok=True)
        pickle_path = f'{software}/models/PLECnn_p5_l1_pdbbind2016_s65536.pickle'
        results = rescoring_folder / 'plecscore_rescoring' / 'rescored_PLECnn.sdf'
        plecscore_rescoring_command = (
            'oddt_cli ' + str(sdf) +
            ' --receptor ' + str(protein_file) +
            ' -n ' + str(ncpus) +
            ' --score_file ' + str(pickle_path) +
            ' -O ' + str(results)
        )
        subprocess.call(plecscore_rescoring_command, shell=True)
        df = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        df.rename(columns={'PLECnn_p5_l1_s65536': kwargs.get(column_name)}, inplace=True)
        df = df[['Pose ID', kwargs.get(column_name)]]
        df.to_csv(rescoring_folder / 'plecscore_rescoring' / 'plecscore_scores.csv', index=False)
        toc = time.perf_counter()
        printlog(f'Rescoring with PLECScore complete in {toc-tic:0.4f}!')
        delete_files(rescoring_folder / 'plecscore_rescoring', 'plecscore_scores.csv')
        return df

    def SCORCH_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        SCORCH_rescoring_folder = rescoring_folder / 'SCORCH_rescoring'
        rescoring_folder / 'SCORCH_rescoring'.mkdir(parents=True, exist_ok=True)
        SCORCH_protein = rescoring_folder / 'SCORCH_rescoring' / "protein.pdbqt"
        printlog('Converting protein file to .pdbqt ...')
        obabel_command = f'obabel -ipdb {protein_file} -O {SCORCH_protein} --partialcharges gasteiger'
        subprocess.call(obabel_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        # Convert ligands to pdbqt
        sdf_file_name = sdf.stem
        printlog(f'Converting SDF file {sdf_file_name}.sdf to .pdbqt files...')
        split_files_folder = rescoring_folder / 'SCORCH_rescoring' / f'split_{sdf_file_name}'
        split_files_folder.mkdir(exist_ok=True)
        num_molecules = parallel_sdf_to_pdbqt(sdf, split_files_folder, ncpus)
        print(f"Converted {num_molecules} molecules.")
        # Run SCORCH
        printlog('Rescoring with SCORCH')
        SCORCH_command = f'python {software}/SCORCH/scorch.py --receptor {SCORCH_protein} --ligand {split_files_folder} --out {rescoring_folder / "SCORCH_rescoring" / "scoring_results.csv"} --threads {ncpus} --return_pose_scores'
        subprocess.call(SCORCH_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        # Clean data
        SCORCH_scores = pd.read_csv(rescoring_folder / 'SCORCH_rescoring' / 'scoring_results.csv')
        SCORCH_scores = SCORCH_scores.rename(columns={'Ligand_ID': 'Pose ID',
                                                    'SCORCH_pose_score': kwargs.get(column_name)})
        SCORCH_scores = SCORCH_scores[[kwargs.get(column_name), 'Pose ID']]
        SCORCH_scores.to_csv(rescoring_folder / 'SCORCH_rescoring' / 'SCORCH_scores.csv', index=False)
        delete_files(rescoring_folder / 'SCORCH_rescoring', 'SCORCH_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with SCORCH complete in {toc-tic:0.4f}!')
        return

    def RTMScore_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        rescoring_folder / 'RTMScore_rescoring'.mkdir(parents=True, exist_ok=True)
        RTMScore_pocket = str(protein_file).replace('.pdb', '_pocket.pdb')
        if ncpus == 1:
            printlog('Rescoring with RTMScore')
            try:
                results = rtmscore(prot=RTMScore_pocket, lig=sdf, output=rescoring_folder / 'RTMScore_rescoring' / 'RTMScore_scores.csv', model=f'{software}/RTMScore/trained_models/rtmscore_model1.pth', ncpus=1)
            except BaseException:
                printlog('RTMScore scoring with pocket failed, scoring with whole protein...')
                results = rtmscore(prot=protein_file, lig=sdf, output=rescoring_folder / 'RTMScore_rescoring' / 'RTMScore_scores.csv', model= f'{software}/RTMScore/trained_models/rtmscore_model1.pth', ncpus=1)
        else:
            printlog('Rescoring with RTMScore')
            split_files_folder = split_sdf(rescoring_folder / 'RTMScore_rescoring', sdf, ncpus * 5)
            split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
            global RTMScore_rescoring_splitted
            
            def RTMScore_rescoring_splitted(split_file, protein_file, ncpus):
                output_file = str(rescoring_folder / 'RTMScore_rescoring' / f'{split_file.stem}_RTMScore.csv')
                try:
                    rtmscore(prot=RTMScore_pocket, lig=split_file, output=output_file, model=str(f'{software}/RTMScore/trained_models/rtmscore_model1.pth'), ncpus=1)
                except BaseException:
                    printlog('RTMScore scoring with pocket failed, scoring with whole protein...')
                    rtmscore(prot=protein_file, lig=split_file, output=output_file, model=str(f'{software}/RTMScore/trained_models/rtmscore_model1.pth'), ncpus=1)
            with concurrent.futures.ProcessPoolExecutor(max_workers=int(ncpus)) as executor:
                jobs = []
                for split_file in tqdm(split_files_sdfs, desc='Submitting RTMScore rescoring jobs', unit='file'):
                    try:
                        job = executor.submit(RTMScore_rescoring_splitted,split_file,protein_file,ncpus)
                        jobs.append(job)
                    except Exception as e:
                        printlog("Error in concurrent futures job creation: " + str(e))
                for job in tqdm(
                        concurrent.futures.as_completed(jobs),
                        total=len(split_files_sdfs),
                        desc='Rescoring with RTMScore',
                        unit='file'):
                    try:
                        res = job.result()
                    except Exception as e:
                        printlog("Error in concurrent futures job run: " + str(e))
            results_dataframes = [pd.read_csv(file) for file in glob.glob(str(rescoring_folder / 'RTMScore_rescoring' / 'split*.csv'))]
            results = pd.concat(results_dataframes)
            results['Pose ID'] = results['Pose ID'].apply(lambda x: x.split('-')[0])
            results.to_csv(rescoring_folder / 'RTMScore_rescoring' / 'RTMScore_scores.csv', index=False)
            delete_files(rescoring_folder / 'RTMScore_rescoring', 'RTMScore_scores.csv')

    def LinF9_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        rescoring_folder / 'LinF9_rescoring'.mkdir(parents=True, exist_ok=True)

        if ncpus == 1:
            printlog('Rescoring with LinF9')
            results = rescoring_folder / 'LinF9_rescoring' / 'rescored_LinF9.sdf'
            LinF9_cmd = (
                f'{software}/smina.static' +
                f' --receptor {protein_file}' +
                f' --ligand {sdf}' +
                f' --out {results}' +
                f' --center_x {pocket_definition["center"][0]}' +
                f' --center_y {pocket_definition["center"][1]}' +
                f' --center_z {pocket_definition["center"][2]}' +
                f' --size_x {pocket_definition["size"][0]}' +
                f' --size_y {pocket_definition["size"][1]}' +
                f' --size_z {pocket_definition["size"][2]}' +
                ' --scoring Lin_F9 --score_only'
            )
            subprocess.call(LinF9_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
            LinF9_rescoring_results = PandasTools.LoadSDF(str(results), idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        else:
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

        with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
            jobs = []
            for split_file in tqdm(split_files_sdfs, desc='Submitting LinF9 rescoring jobs', unit='file'):
                try:
                    job = executor.submit(LinF9_rescoring_splitted, split_file, protein_file, pocket_definition)
                    jobs.append(job)
                except Exception as e:
                    printlog("Error in concurrent futures job creation: " + str(e))
            for job in tqdm(concurrent.futures.as_completed(jobs), total=len(split_files_sdfs), desc='Rescoring with LinF9', unit='file'):
                try:
                    res = job.result()
                except Exception as e:
                    printlog("Error in concurrent futures job run: " + str(e))

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

        LinF9_rescoring_results.rename(columns={'minimizedAffinity': kwargs.get(column_name)}, inplace=True)
        LinF9_rescoring_results = LinF9_rescoring_results[['Pose ID', kwargs.get(column_name)]]
        LinF9_rescoring_results.to_csv(rescoring_folder / 'LinF9_rescoring' / 'LinF9_scores.csv', index=False)
        delete_files(rescoring_folder / 'LinF9_rescoring', 'LinF9_scores.csv')
        toc = time.perf_counter()
        printlog(f'Rescoring with LinF9 complete in {toc-tic:0.4f}!')
        return LinF9_rescoring_results

    def AAScore_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        rescoring_folder / 'AAScore_rescoring'.mkdir(parents=True, exist_ok=True)
        pocket = protein_file.replace('.pdb', '_pocket.pdb')

        if ncpus == 1:
            printlog('Rescoring with AAScore')
            results = rescoring_folder / 'AAScore_rescoring' / 'rescored_AAScore.csv'
            AAscore_cmd = f'python software/AA-Score-Tool-main/AA_Score.py --Rec {pocket} --Lig {sdf} --Out {results}'
            subprocess.call(AAscore_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
            AAScore_rescoring_results = pd.read_csv(results, delimiter='\t', header=None, names=['Pose ID', 'AAScore'])
        else:
            split_files_folder = split_sdf(rescoring_folder / 'AAScore_rescoring', sdf, ncpus)
            split_files_sdfs = [Path(split_files_folder) / f for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
            global AAScore_rescoring_splitted

            def AAScore_rescoring_splitted(split_file):
                AAScore_folder = rescoring_folder / 'AAScore_rescoring'
                results = AAScore_folder / f'{split_file.stem}_AAScore.csv'
                AAScore_cmd = f'python software/AA-Score-Tool-main/AA_Score.py --Rec {pocket} --Lig {split_file} --Out {results}'
                try:
                    subprocess.call( AAScore_cmd,shell=True,stdout=DEVNULL,stderr=STDOUT)
                except Exception as e:
                    printlog('AAScore rescoring failed: ' + str(e))

            with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
                jobs = []
                for split_file in tqdm(split_files_sdfs, desc='Submitting AAScore rescoring jobs', unit='file'):
                    try:
                        job = executor.submit(AAScore_rescoring_splitted, split_file)
                        jobs.append(job)
                    except Exception as e:
                        printlog("Error in concurrent futures job creation: " + str(e))
                for job in tqdm(concurrent.futures.as_completed(jobs), total=len(split_files_sdfs), desc='Rescoring with AAScore', unit='file'):
                    try:
                        res = job.result()
                    except Exception as e:
                        printlog("Error in concurrent futures job run: " + str(e))

            try:
                AAScore_dataframes = [pd.read_csv(rescoring_folder / 'AAScore_rescoring' / file,
                                                    delimiter='\t',
                                                    header=None,
                                                    names=['Pose ID', kwargs.get(column_name)]) for file in os.listdir(rescoring_folder / 'AAScore_rescoring') if file.startswith('split') and file.endswith('.csv')
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

    def KORPL_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        (rescoring_folder / 'KORPL_rescoring').mkdir(parents=True, exist_ok=True)
        if ncpus == 1:
            printlog('Rescoring with KORPL')
            df = PandasTools.LoadSDF(str(sdf), idName='Pose ID', molColName=None)
            df = df[['Pose ID']]
            korpl_command = (f'{software}/KORP-PL' +
                            ' --receptor ' + str(protein_file) +
                            ' --ligand ' + str(sdf) +
                            ' --sdf')
            process = subprocess.Popen(
                korpl_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True)
            stdout, stderr = process.communicate()
            energies = []
            output = stdout.decode().splitlines()
            for line in output:
                if line.startswith('model'):
                    parts = line.split(',')
                    energy = round(float(parts[1].split('=')[1]), 2)
                    energies.append(energy)
            df[kwargs.get(column_name)] = energies
            df.to_csv(rescoring_folder / 'KORPL_rescoring' / 'KORPL_scores.csv', index=False)
        else:
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
                df['KORPL'] = energies
                output_csv = str(rescoring_folder / 'KORPL_rescoring' / (str(split_file.stem) + '_scores.csv'))
                df.to_csv(output_csv, index=False)
                return
            
            with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
                jobs = []
                for split_file in tqdm(split_files_sdfs, desc='Submitting KORPL rescoring jobs', unit='file'):
                    try:
                        job = executor.submit(KORPL_rescoring_splitted, split_file, protein_file)
                        jobs.append(job)
                    except Exception as e:
                        printlog("Error in concurrent futures job creation: " + str(e))
                for job in tqdm(concurrent.futures.as_completed(jobs), total=len(split_files_sdfs), desc='Rescoring with KORPL', unit='file'):
                    try:
                        res = job.result()
                    except Exception as e:
                        printlog("Error in concurrent futures job run: " + str(e))
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

    def ConvexPLR_rescoring(sdf, ncpus, **kwargs):
        tic = time.perf_counter()
        (rescoring_folder / 'ConvexPLR_rescoring').mkdir(parents=True, exist_ok=True)
        if ncpus == 1:
            printlog('Rescoring with ConvexPLR')
            df = PandasTools.LoadSDF(str(sdf), idName='Pose ID', molColName=None)
            df = df[['Pose ID']]
            ConvexPLR_command = (f'{software}/Convex-PL' +
                                ' --receptor ' + str(protein_file) +
                                ' --ligand ' + str(sdf) +
                                ' --sdf --regscore')
            process = subprocess.Popen(ConvexPLR_command,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        shell=True)
            stdout, stderr = process.communicate()
            energies = []
            output = stdout.decode().splitlines()
            for line in output:
                if line.startswith('model'):
                    parts = line.split(',')
                    energy = round(float(parts[1].split('=')[1]), 2)
                    energies.append(energy)
            df[kwargs.get(column_name)] = energies
            df.to_csv(rescoring_folder / 'ConvexPLR_rescoring' / 'ConvexPLR_scores.csv', index=False)
        
        else:
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
                process = subprocess.Popen(
                    ConvexPLR_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True)
                stdout, stderr = process.communicate()
                energies = []
                output = stdout.decode().splitlines()
                for line in output:
                    if line.startswith('model'):
                        parts = line.split(',')
                        energy = round(float(parts[1].split('=')[1]), 2)
                        energies.append(energy)
                df['ConvexPLR'] = energies
                output_csv = str(rescoring_folder / 'ConvexPLR_rescoring' / (str(split_file.stem) + '_scores.csv'))
                df.to_csv(output_csv, index=False)
                return
            
            with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
                jobs = []
                for split_file in tqdm(split_files_sdfs, desc='Submitting ConvexPLR rescoring jobs', unit='file'):
                    try:
                        job = executor.submit(ConvexPLR_rescoring_splitted, split_file, protein_file)
                        jobs.append(job)
                    except Exception as e:
                        printlog("Error in concurrent futures job creation: " + str(e))
                for job in tqdm(concurrent.futures.as_completed(jobs), total=len(split_files_sdfs), desc='Rescoring with ConvexPLR', unit='file'):
                    try:
                        res = job.result()
                    except Exception as e:
                        printlog("Error in concurrent futures job run: " + str(e))
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

    # Read the JSON file into a dictionary
    with open('scripts/rescoring_functions.json', 'r') as json_file:
        rescoring_functions = json.load(json_file)

    skipped_functions = []
    for function in functions:
        if function in rescoring_functions:
            score_file_path = rescoring_folder / f'{function}_rescoring' / f'{function}_scores.csv'
            if not score_file_path.is_file():
                rescoring_functions[function]['function_name'](clustered_sdf, ncpus, **rescoring_functions[function][parameters])
            else:
                skipped_functions.append(function)
        else:
            printlog(f"'{function}' not found in the JSON file.")
    if skipped_functions:
        printlog(f'Skipping functions: {", ".join(skipped_functions)}')

    score_files = [f'{function}_scores.csv' for function in functions]
    printlog(f'Combining all scores for {rescoring_folder}')
    csv_files = [
        file for file in (
            rescoring_folder.rglob('*.csv')) if file.name in score_files]
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
