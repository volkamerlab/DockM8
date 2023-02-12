from rdkit.Chem import PandasTools
import pandas as pd

def calculate_EFs(w_dir, docking_library):
    original_df = PandasTools.LoadSDF(docking_library, molColName='Molecule', idName='ID')
    original_df = original_df[['ID', 'Activity']]
    ranking_results = pd.read_csv(w_dir+'/temp/consensus/method_results.csv')
    merged_df = ranking_results.merge(original_df, on='ID')
    merged_df['Activity'] = pd.to_numeric(merged_df['Activity'])
    method_list = ranking_results.columns.tolist()[1:]
    method_ranking = {'ECR':False, 'Zscore':False, 'RbV':False, 'RbR':True}
    EF_results = pd.DataFrame()
    for method in method_list:
        asc = [method_ranking[key] for key in method_ranking if key in method][0]
        sorted_df = merged_df.sort_values(method, ascending = asc)
        N10_percent = round(0.10 * len(sorted_df))
        N1_percent = round(0.01 * len(sorted_df))
        N100_percent = len(sorted_df)
        Hits10_percent = sorted_df.head(N10_percent)['Activity'].sum()
        Hits1_percent = sorted_df.head(N1_percent)['Activity'].sum()
        Hits100_percent = sorted_df['Activity'].sum()
        ef10 = round((Hits10_percent/N10_percent)*(N100_percent/Hits100_percent),2)
        ef1 = round((Hits1_percent/N1_percent)*(N100_percent/Hits100_percent),2)
        EF_results.loc[method, 'EF10%'] = ef10
        EF_results.loc[method, 'EF1%'] = ef1
    EF_results.to_csv(w_dir+'/temp/consensus/enrichement_factors.csv')
    
def calculate_EF_column(column_name, df):
    sorted_df = df.sort_values(column_name, ascending = False)
    N10_percent = round(0.10 * len(sorted_df))
    N1_percent = round(0.01 * len(sorted_df))
    N100_percent = len(df)
    Hits10_percent = sorted_df.head(N10_percent)['Activity'].sum()
    Hits1_percent = sorted_df.head(N1_percent)['Activity'].sum()
    Hits100_percent = sorted_df['Activity'].sum()
    ef10 = round((Hits10_percent/N10_percent)*(N100_percent/Hits100_percent),2)
    ef1 = round((Hits1_percent/N1_percent)*(N100_percent/Hits100_percent),2)
    print(f'EF10% for {column_name} : {ef10}')
    print(f'EF1% for {column_name} : {ef1}')
