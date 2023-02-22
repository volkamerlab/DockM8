import os
import shutil
import subprocess
from subprocess import DEVNULL, STDOUT, PIPE
import pandas as pd
import functools
from rdkit import Chem
from rdkit.Chem import PandasTools
import oddt
from oddt.scoring.functions import NNScore
from oddt.scoring.functions import RFScore
from oddt.scoring.functions.PLECscore import PLECscore
from tqdm import tqdm
import multiprocessing
import concurrent.futures
import time
from scripts.utilities import *
from IPython.display import display

#TODO: add new scoring functions:
# _ECIF
# _LinF9
# _SIEVE_Score (no documentation)
# _

def rescore_all(w_dir, protein_file, ref_file, software, clustered_sdf, functions, mp, ncpus):
    tic = time.perf_counter()
    rescoring_folder_name = os.path.basename(clustered_sdf).split('/')[-1]
    rescoring_folder_name = rescoring_folder_name.replace('.sdf', '')
    rescoring_folder = w_dir+'/temp/rescoring_'+rescoring_folder_name
    create_temp_folder(rescoring_folder)
    def gnina_rescoring(sdf, mp):
        tic = time.perf_counter()
        create_temp_folder(rescoring_folder+'/gnina_rescoring/')
        cnn = 'crossdock_default2018'
        if mp == 0:
            print('Rescoring with GNINA')
            results = rescoring_folder+'/gnina_rescoring/'+'rescored_'+cnn+'.sdf'
            gnina_cmd = 'cd '+software+' && ./gnina -r '+protein_file+' -l '+sdf+' --autobox_ligand '+ref_file+' -o '+results+' --cnn '+cnn+' --score_only'
            subprocess.call(gnina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
            gnina_rescoring_results = PandasTools.LoadSDF(results, idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        else:
            print(f'Splitting {os.path.basename(sdf)}...')
            split_files_folder = split_sdf(rescoring_folder+'/gnina_rescoring', sdf, ncpus)
            split_files_sdfs = [os.path.join(split_files_folder, f) for f in os.listdir(split_files_folder) if f.endswith('.sdf')]
            print('Rescoring with GNINA')
            global gnina_rescoring_splitted
            def gnina_rescoring_splitted(split_file, protein_file, ref_file, software):
                gnina_folder = rescoring_folder+'/gnina_rescoring/'
                results = gnina_folder+os.path.basename(split_file).split('.')[0]+'_gnina.sdf'
                gnina_cmd = 'cd '+software+' && ./gnina -r '+protein_file+' -l '+sdf+' --autobox_ligand '+ref_file+' -o '+results+' --cnn '+cnn+' --score_only'
                try:
                    subprocess.call(gnina_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
                except Exception as e:
                    print('GNINA rescoring failed: '+e)
                return
            with concurrent.futures.ProcessPoolExecutor(max_workers=ncpus) as executor:
                jobs = []
                for split_file in tqdm(split_files_sdfs, desc='Submitting GNINA rescoring jobs', unit='file'):
                    try:
                        job = executor.submit(gnina_rescoring_splitted, split_file, protein_file, ref_file, software)
                        jobs.append(job)
                    except Exception as e:
                        print("Error in concurrent futures job creation: ", str(e))
                for job in tqdm(concurrent.futures.as_completed(jobs), total=len(split_files_sdfs), desc='Rescoring with GNINA', unit='file'):
                    try:
                        res = job.result()
                    except Exception as e:
                        print("Error in concurrent futures job run: ", str(e))
            #with multiprocessing.Pool(processes=(multiprocessing.cpu_count()-2)) as pool:
            #    pool.starmap(gnina_rescoring_splitted, [(split_file, protein_file, ref_file, software) for split_file in split_files_sdfs])
            try:
                gnina_dataframes = [PandasTools.LoadSDF(rescoring_folder+'/gnina_rescoring/'+file, idName='Pose ID', molColName=None,includeFingerprints=False, embedProps=False, removeHs=False, strictParsing=True) for file in os.listdir(rescoring_folder+'/gnina_rescoring/') if file.startswith('split') and file.endswith('.sdf')]
            except Exception as e:
                print('ERROR: Failed to Load GNINA rescoring SDF file!')
                print(e)
            try:
                gnina_rescoring_results = pd.concat(gnina_dataframes)
            except Exception as e:
                print('ERROR: Could not combine GNINA rescored poses')
                print(e)
            else:
                for file in os.listdir(split_files_folder):
                    if file.startswith('split'):
                        os.remove(os.path.join(split_files_folder, file))
        gnina_rescoring_results.rename(columns = {'minimizedAffinity':'GNINA_Affinity', 'CNNscore':'GNINA_CNN_Score', 'CNNaffinity':'GNINA_CNN_Affinity'}, inplace = True)
        gnina_rescoring_results = gnina_rescoring_results[['Pose ID', 'GNINA_Affinity', 'GNINA_CNN_Score', 'GNINA_CNN_Affinity']]
        gnina_rescoring_results.to_csv(rescoring_folder+'/gnina_rescoring/gnina_scores.csv')
        toc = time.perf_counter()
        print(f'Rescoring with GNINA complete in {toc-tic:0.4f}!')
        return gnina_rescoring_results
    def vinardo_rescoring(sdf, mp):
        display(sdf)
        tic = time.perf_counter()
        print('Rescoring with Vinardo')
        create_temp_folder(rescoring_folder+'/vinardo_rescoring/')
        results = rescoring_folder+'/vinardo_rescoring/'+'rescored_vinardo.sdf'
        vinardo_cmd = 'cd '+software+' && ./gnina -r '+protein_file+' -l '+sdf+' --autobox_ligand '+ref_file+' -o '+results+' --score_only --scoring vinardo --cnn_scoring none'
        subprocess.call(vinardo_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        vinardo_rescoring_results = PandasTools.LoadSDF(results, idName='Pose ID', molColName=None, includeFingerprints=False, removeHs=False)
        vinardo_rescoring_results.rename(columns = {'minimizedAffinity':'Vinardo_Affinity'}, inplace = True)
        vinardo_rescoring_results = vinardo_rescoring_results[['Pose ID', 'Vinardo_Affinity']]
        vinardo_rescoring_results.to_csv(rescoring_folder+'/vinardo_rescoring/vinardo_scores.csv')
        toc = time.perf_counter()
        print(f'Rescoring with Vinardo complete in {toc-tic:0.4f}!')
        return vinardo_rescoring_results
    def AD4_rescoring(sdf, mp):
        tic = time.perf_counter()
        print('Rescoring with AD4')
        create_temp_folder(rescoring_folder+'/AD4_rescoring/')
        results = rescoring_folder+'/AD4_rescoring/'+'rescored_AD4.sdf'
        AD4_cmd = 'cd '+software+' && ./gnina -r '+protein_file+' -l '+sdf+' --autobox_ligand '+ref_file+' -o '+results+' --score_only --scoring ad4_scoring --cnn_scoring none'
        subprocess.call(AD4_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        AD4_rescoring_results = PandasTools.LoadSDF(results, idName='Pose ID', molColName='None', includeFingerprints=False, removeHs=False)
        AD4_rescoring_results.rename(columns = {'minimizedAffinity':'AD4_Affinity'}, inplace = True)
        AD4_rescoring_results = AD4_rescoring_results[['Pose ID', 'AD4_Affinity']]
        AD4_rescoring_results.to_csv(rescoring_folder+f'/AD4_rescoring/AD4_scores.csv')
        toc = time.perf_counter()
        print(f'Rescoring with AD4 complete in {toc-tic:0.4f}!')
        return AD4_rescoring_results
    def rfscore_rescoring(sdf, mp):
        tic = time.perf_counter()
        print('Rescoring with RFScoreVS')
        create_temp_folder(rescoring_folder+'/rfscorevs_rescoring')
        results_path = rescoring_folder+'/rfscorevs_rescoring/rfscorevs_scores.csv'
        if mp == 1 :
            rfscore_cmd = 'cd '+software+' && ./rf-score-vs --receptor '+protein_file+' '+sdf+' -O '+results_path+' -n '+str(int(multiprocessing.cpu_count()-2))
        else:
            rfscore_cmd = 'cd '+software+' && ./rf-score-vs --receptor '+protein_file+' '+sdf+' -O '+results_path+' -n 1'
        subprocess.call(rfscore_cmd, shell=True, stdout=DEVNULL, stderr=STDOUT)
        rfscore_results = pd.read_csv(results_path, delimiter=',', header=0)
        rfscore_results = rfscore_results.rename(columns={'name': 'Pose ID', 'RFScoreVS_v2':'RFScoreVS'})
        rfscore_results.to_csv(rescoring_folder+'/rfscorevs_rescoring/rfscorevs_scores.csv')
        toc = time.perf_counter()
        print(f'Rescoring with RF-Score-VS complete in {toc-tic:0.4f}!')
        return rfscore_results
    def plp_rescoring(sdf, mp):
        tic = time.perf_counter()
        print('Rescoring with PLP')
        plants_search_speed = 'speed1'
        ants = '20'
        plp_rescoring_folder = rescoring_folder+'/plp_rescoring/'
        create_temp_folder(plp_rescoring_folder)
        #Read protein and ref files generated during PLANTS docking
        plants_protein_mol2 = w_dir+'/temp/plants/protein.mol2'
        plants_ref_mol2 = w_dir+'/temp/plants/ref.mol2'
        #Convert clustered ligand file to .mol2 using open babel
        plants_ligands_mol2 = plp_rescoring_folder+'/ligands.mol2'
        try:
            obabel_command = 'obabel -isdf '+sdf+' -O '+plants_ligands_mol2
            os.system(obabel_command)
        except:
            print('ERROR: Failed to convert clustered library file to .mol2!')
        #Determine binding site coordinates
        plants_binding_site_command = 'cd '+software+' && ./PLANTS --mode bind '+plants_ref_mol2+' 6'
        run_plants_binding_site = subprocess.Popen(plants_binding_site_command, shell = True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = run_plants_binding_site.communicate()
        output_plants_binding_site = output.decode('utf-8').splitlines()
        keep = []
        for l in output_plants_binding_site:
            if l.startswith('binding'):
                keep.append(l)
            else:
                pass
        binding_site_center = keep[0].split()
        binding_site_radius = keep[1].split()
        binding_site_radius = binding_site_radius[1]
        binding_site_x = binding_site_center[1]
        binding_site_y = binding_site_center[2]
        binding_site_z = str(binding_site_center[3]).replace('+', '')
        results_csv_location = plp_rescoring_folder+'results/ranking.csv'
        #Generate plants config file
        plp_rescoring_config_path_txt = plp_rescoring_folder+'config.txt'
        plp_config = ['# search algorithm\n',
        'search_speed '+plants_search_speed+'\n',
        'aco_ants '+ants+'\n',
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
        'protein_file '+plants_protein_mol2+'\n',
        'ligand_file '+plants_ligands_mol2+'\n',

        '# output\n',
        'output_dir '+plp_rescoring_folder+'results\n',

        '# write single mol2 files (e.g. for RMSD calculation)\n',
        'write_multi_mol2 1\n',

        '# binding site definition\n',
        'bindingsite_center '+binding_site_x+' '+binding_site_y+' '+binding_site_z+'+\n',
        'bindingsite_radius '+binding_site_radius+'\n',

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
        #Write config file
        plp_rescoring_config_path_config = plp_rescoring_config_path_txt.replace('.txt', '.config')
        with open(plp_rescoring_config_path_config, 'w') as configwriter:
            configwriter.writelines(plp_config)
        configwriter.close()
        #Run PLANTS docking
        plp_rescoring_command = 'cd '+software+' && ./PLANTS --mode rescore '+plp_rescoring_config_path_config
        subprocess.call(plp_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        #Fetch results
        results_csv_location = plp_rescoring_folder+'results/ranking.csv'
        plp_results = pd.read_csv(results_csv_location, sep=',', header=0)
        plp_results.rename(columns = {'TOTAL_SCORE':'PLP'}, inplace = True)
        for i, row in plp_results.iterrows():
            split = row['LIGAND_ENTRY'].split('_')
            plp_results.loc[i, ['Pose ID']] = split[0]+'_'+split[1]+'_'+split[2]
        plp_rescoring_output = plp_results[['Pose ID', 'PLP']]
        plp_rescoring_output.to_csv(rescoring_folder+'/plp_rescoring/plp_scores.csv')
        os.remove(plants_ligands_mol2)
        toc = time.perf_counter()
        print(f'Rescoring with PLP complete in {toc-tic:0.4f}!')
        return plp_rescoring_output
    def chemplp_rescoring(sdf, mp):
        tic = time.perf_counter()
        print('Rescoring with CHEMPLP')
        plants_search_speed = 'speed1'
        ants = '20'
        chemplp_rescoring_folder = rescoring_folder+'/chemplp_rescoring/'
        create_temp_folder(chemplp_rescoring_folder)
        #Read protein and ref files generated during PLANTS docking
        plants_protein_mol2 = w_dir+'/temp/plants/protein.mol2'
        plants_ref_mol2 = w_dir+'/temp/plants/ref.mol2'
        #Convert clustered ligand file to .mol2 using open babel
        plants_ligands_mol2 = chemplp_rescoring_folder+'/ligands.mol2'
        try:
            obabel_command = 'obabel -isdf '+sdf+' -O '+plants_ligands_mol2
            os.system(obabel_command)
        except:
            print('ERROR: Failed to convert clustered library file to .mol2!')
        #Determine binding site coordinates
        plants_binding_site_command = 'cd '+software+' && ./PLANTS --mode bind '+plants_ref_mol2+' 6'
        run_plants_binding_site = subprocess.Popen(plants_binding_site_command, shell = True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = run_plants_binding_site.communicate()
        output_plants_binding_site = output.decode('utf-8').splitlines()
        keep = []
        for l in output_plants_binding_site:
            if l.startswith('binding'):
                keep.append(l)
            else:
                pass
        binding_site_center = keep[0].split()
        binding_site_radius = keep[1].split()
        binding_site_radius = binding_site_radius[1]
        binding_site_x = binding_site_center[1]
        binding_site_y = binding_site_center[2]
        binding_site_z = binding_site_center[3].replace('+', '')
        #Generate plants config file
        chemplp_rescoring_config_path_txt = chemplp_rescoring_folder+'config.txt'
        chemplp_config = ['# search algorithm\n',
        'search_speed '+plants_search_speed+'\n',
        'aco_ants '+ants+'\n',
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
        'protein_file '+plants_protein_mol2+'\n',
        'ligand_file '+plants_ligands_mol2+'\n',

        '# output\n',
        'output_dir '+chemplp_rescoring_folder+'results\n',

        '# write single mol2 files (e.g. for RMSD calculation)\n',
        'write_multi_mol2 1\n',

        '# binding site definition\n',
        'bindingsite_center '+binding_site_x+' '+binding_site_y+' '+binding_site_z+'+\n',
        'bindingsite_radius '+binding_site_radius+'\n',

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
        #Write config file
        chemplp_rescoring_config_path_config = chemplp_rescoring_config_path_txt.replace('.txt', '.config')
        with open(chemplp_rescoring_config_path_config, 'w') as configwriter:
            configwriter.writelines(chemplp_config)
        configwriter.close()
        #Run PLANTS docking
        chemplp_rescoring_command = 'cd '+software+' && ./PLANTS --mode rescore '+chemplp_rescoring_config_path_config
        subprocess.call(chemplp_rescoring_command, shell=True, stdout=DEVNULL, stderr=STDOUT)
        #Fetch results
        results_csv_location = chemplp_rescoring_folder+'results/ranking.csv'
        chemplp_results = pd.read_csv(results_csv_location, sep=',', header=0)
        chemplp_results.rename(columns = {'TOTAL_SCORE':'CHEMPLP'}, inplace = True)
        for i, row in chemplp_results.iterrows():
            split = row['LIGAND_ENTRY'].split('_')
            chemplp_results.loc[i, ['Pose ID']] = split[0]+'_'+split[1]+'_'+split[2]
        chemplp_rescoring_output = chemplp_results[['Pose ID', 'CHEMPLP']]
        chemplp_rescoring_output.to_csv(rescoring_folder+'/chemplp_rescoring/chemplp_scores.csv')
        os.remove(plants_ligands_mol2)
        toc = time.perf_counter()
        print(f'Rescoring with CHEMPLP complete in {toc-tic:0.4f}!')
        return chemplp_rescoring_output
    def oddt_nnscore_rescoring(sdf, mp):
        tic = time.perf_counter()
        print('Rescoring with NNScore')
        rescorers = {'nnscore':NNScore.nnscore()}
        nnscore_rescoring_folder = rescoring_folder+'/nnscore_rescoring/'
        create_temp_folder(nnscore_rescoring_folder)
        scorer = rescorers['nnscore']
        pickle = software+'/NNScore_pdbbind2016.pickle'
        scorer = scorer.load(pickle)
        oddt_prot=next(oddt.toolkit.readfile('pdb', protein_file))
        oddt_prot.protein = True
        scorer.set_protein(oddt_prot)
        re_scores = []
        df = PandasTools.LoadSDF(sdf, idName='Pose ID', molColName='Molecule', removeHs=False)
        if mp == 0:
            for mol in tqdm(df['Molecule'], desc='Rescoring with NNScore', unit='mol'):
                Chem.MolToMolFile(mol, nnscore_rescoring_folder+'/temp.sdf')
                oddt_lig = next(oddt.toolkit.readfile('sdf', nnscore_rescoring_folder+'/temp.sdf'))
                scored_mol = scorer.predict_ligand(oddt_lig)
                re_scores.append(float(scored_mol.data['nnscore']))
        else:
            global score_mol
            def score_mol(mol):
                oddt_mol = oddt.toolkit.Molecule(mol)
                scored_mol = scorer.predict_ligand(oddt_mol)
                return float(scored_mol.data['nnscore'])
            with multiprocessing.Pool() as p:
                re_scores = p.map(score_mol, df['Molecule'])
        df['NNScore']=re_scores
        df = df[['Pose ID', 'NNScore']]
        df.to_csv(rescoring_folder+'/nnscore_rescoring/nnscore_scores.csv')
        toc = time.perf_counter()
        print(f'Rescoring with NNScore complete in {toc-tic:0.4f}!')
        return df
    def oddt_plecscore_rescoring(sdf, mp):
        tic = time.perf_counter()
        print('Rescoring with PLECscore')
        rescorers = {'PLECnn_p5_l1_s65536':PLECscore(version='nn')}
        plecscore_rescoring_folder = rescoring_folder+'/plecscore_rescoring/'
        create_temp_folder(plecscore_rescoring_folder)
        scorer = rescorers['PLECnn_p5_l1_s65536']
        pickle = software+'/PLECnn_p5_l1_2016.pickle'
        scorer = scorer.load(pickle)
        oddt_prot=next(oddt.toolkit.readfile('pdb', protein_file.replace('.pdb','_pocket.pdb')))
        oddt_prot.protein = True
        scorer.set_protein(oddt_prot)
        re_scores = []
        df = PandasTools.LoadSDF(sdf, idName='Pose ID', molColName='Molecule', removeHs=False)
        if mp == 0:
            for mol in tqdm(df['Molecule'], desc='Rescoring with PLECScore', unit='mol'):
                Chem.MolToMolFile(mol, plecscore_rescoring_folder+'/temp.sdf')
                oddt_lig = next(oddt.toolkit.readfile('sdf', plecscore_rescoring_folder+'/temp.sdf'))
                scored_mol = scorer.predict_ligand(oddt_lig)
                re_scores.append(float(scored_mol.data['PLECnn_p5_l1_s65536']))
        else:
            global score_mol
            def score_mol(mol):
                oddt_mol = oddt.toolkit.Molecule(mol)
                scored_mol = scorer.predict_ligand(oddt_mol)
                return float(scored_mol.data['PLECnn_p5_l1_s65536'])
            with multiprocessing.Pool() as p:
                re_scores = p.map(score_mol, df['Molecule'])
        df['PLECnn']=re_scores
        df = df[['Pose ID', 'PLECnn']]
        df.to_csv(rescoring_folder+'/plecscore_rescoring/plecscore_scores.csv')
        toc = time.perf_counter()
        print(f'Rescoring with PLECScore complete in {toc-tic:0.4f}!')
        return df
    def SCORCH_rescoring(clustered_sdf):
        tic = time.perf_counter()
        SCORCH_rescoring_folder = rescoring_folder+'/SCORCH_rescoring/'
        create_temp_folder(SCORCH_rescoring_folder)
        #Convert protein file to .mol2 using open babel
        SCORCH_protein = SCORCH_rescoring_folder+"protein.pdbqt"
        try:
            obabel_command = 'obabel -ipdb '+protein_file+' -O '+SCORCH_protein+' --partialcharges gasteiger'
            os.system(obabel_command)
        except:
            print('ERROR: Failed to convert protein file to .pdbqt!')
        SCORCH_ligands = SCORCH_rescoring_folder+"ligands.pdbqt"
        try:
            obabel_command = 'obabel -isdf '+clustered_sdf+' -O '+SCORCH_ligands+' --partialcharges gasteiger'
            os.system(obabel_command)
        except:
            print('ERROR: Failed to convert ligands to .pdbqt!')
        try:
            SCORCH_command = 'python '+software+'/SCORCH-main/scorch.py --receptor '+SCORCH_protein+' --ligand '+SCORCH_ligands+' --out '+SCORCH_rescoring_folder+'scoring_results.csv --threads 8 --verbose --return_pose_scores'
            print(SCORCH_command)
            os.system(SCORCH_command)
        except:
            print('ERROR: Failed to run SCORCH!')
        toc = time.perf_counter()
        print(f'Rescoring with SCORCH complete in {toc-tic:0.4f}!')
        return    
    rescoring_functions = {'gnina': gnina_rescoring, 'vinardo': vinardo_rescoring, 'AD4': AD4_rescoring, 
                        'rfscorevs': rfscore_rescoring, 'plp': plp_rescoring, 'chemplp': chemplp_rescoring,
                        'nnscore': oddt_nnscore_rescoring, 'plecscore': oddt_plecscore_rescoring}
    for function in functions:
        if os.path.isdir(rescoring_folder+f'/{function}_rescoring') == False:
            rescoring_functions[function](clustered_sdf, mp)
        else:
            print(f'/{function}_rescoring folder already exists, skipping {function} rescoring')
    if os.path.isfile(rescoring_folder+'/allposes_rescored.csv') == False:
        score_files = [f'{function}_scores.csv' for function in functions]
        print(f'Combining all score for {rescoring_folder}')
        csv_files = [os.path.join(subdir, file) for subdir, dirs, files in os.walk(rescoring_folder) for file in files if file in score_files]
        csv_dfs = [pd.read_csv(f, index_col=0) for f in csv_files]
        combined_dfs = csv_dfs[0]
        for df in tqdm(csv_dfs[1:], desc='Combining scores', unit='files'):
            combined_dfs = pd.merge(combined_dfs, df, left_on='Pose ID', right_on='Pose ID', how='outer')
        first_column = combined_dfs.pop('Pose ID')
        combined_dfs.insert(0, 'Pose ID', first_column)
        columns=combined_dfs.columns
        col=columns[1:]
        for c in col.tolist():
            if c == 'Pose ID':
                pass
            if combined_dfs[c].dtypes is not float:
                combined_dfs[c] = combined_dfs[c].apply(pd.to_numeric, errors='coerce')
            else:
                pass
        combined_dfs.to_csv(rescoring_folder+'/allposes_rescored.csv', index=False)
    toc = time.perf_counter()
    print(f'Rescoring complete in {toc-tic:0.4f}!')
    return