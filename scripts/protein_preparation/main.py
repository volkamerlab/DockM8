import sys
from pathlib import Path

# Search for 'DockM8' in parent directories
dockm8_path = next(
    (p / "DockM8" for p in Path(__file__).resolve().parents if (p / "DockM8").is_dir()),
    None,
)
sys.path.append(str(dockm8_path))

from scripts.protein_preparation.fetching.fetch_alphafold import (
    fetch_alphafold_structure,
)
from scripts.protein_preparation.fetching.fetch_pdb import fetch_pdb_structure
from scripts.protein_preparation.fixing.pdb_fixer import fix_pdb_file
from scripts.protein_preparation.protonation.protonate_protoss import (
    protonate_protein_protoss,
)
from scripts.protein_preparation.structure_assessment.edia import get_best_chain_edia
from scripts.utilities import printlog


def prepare_protein(
    input: Path,
    input_type: str = "File",
    output_dir: Path = None,
    select_best_chain: bool = True,
    fix_protein: bool = True,
    fix_nonstandard_residues: bool = True,
    fix_missing_residues: bool = True,
    add_missing_hydrogens_pH: float = 7.0,
    remove_hetero: bool = True,
    remove_water: bool = True,
    protonate: bool = True,
) -> Path:
    """
    Prepare a protein structure by performing various modifications.

    Args:
        input (str or Path): The input value. It can be a PDB code, Uniprot code, or file path.
        input_type (str, optional): The type of input. Can be 'PDB', 'Uniprot', or 'File'. Default is 'File'.
        output_dir (str or Path, optional): The directory where the prepared protein structure will be saved. If not provided, the same directory as the input file will be used.
        select_best_chain (bool, optional): Whether to select the best chain from the input structure. Only applicable for PDB input. Default is True.
        fix_protein (bool, optional): Whether to fix the protein structure. Default is True.
        fix_nonstandard_residues (bool, optional): Whether to fix nonstandard residues in the protein structure. Default is True.
        fix_missing_residues (bool, optional): Whether to fix missing residues in the protein structure. Default is True.
        add_missing_hydrogens_pH (float, optional): The pH value for adding missing hydrogens. Default is 7.0.
        remove_hetero (bool, optional): Whether to remove heteroatoms from the protein structure. Default is True.
        remove_water (bool, optional): Whether to remove water molecules from the protein structure. Default is True.
        protonate (bool, optional): Whether to protonate the protein structure. Default is True.

    Returns:
        Path: The path to the prepared protein structure.
    """

    if not input_type:
        if len(input) == 4 and input.isalnum():
            input_type = "PDB"
        elif len(input) == 6 and input.isalnum():
            input_type = "Uniprot"
        else:
            # Check if the input is a valid path
            if not Path(input).is_file():
                raise ValueError("Input file is an invalid file path.")
            else:
                input_type = "File"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Check if the input type is valid
    if select_best_chain and input_type.upper() != "PDB":
        printlog(
            "Selecting the best chain is only supported for PDB input. Turning of the best chain selection ..."
        )
        select_best_chain = False
    # Check if protonation is required
    if (
        add_missing_hydrogens_pH is None
        or add_missing_hydrogens_pH == 0.0
        and not protonate
    ):
        printlog(
            "Protonating with Protoss or PDBFixer is required for reliable results. Setting protonate to True."
        )
        protonate = True

    # Fetch the protein structure
    if input_type.upper() == "PDB":
        # Ensure the pdb code is in the right format (4 letters or digits)
        pdb_code = input.strip().upper()
        if len(pdb_code) != 4 or not pdb_code.isalnum():
            raise ValueError(
                "Invalid pdb code format. It should be 4 letters or digits."
            )
        if select_best_chain:
            # Get the best chain using EDIA
            step1_pdb = get_best_chain_edia(pdb_code, output_dir)
        else:
            # Get PDB structure
            step1_pdb = fetch_pdb_structure(input, output_dir)
    elif input_type.upper() == "UNIPROT":
        # Fetch the Uniprot structure
        uniprot_code = input
        step1_pdb = fetch_alphafold_structure(uniprot_code, output_dir)
    else:
        # Assume input is a file path
        step1_pdb = Path(input)

    # Fix the protein structure
    if (
        fix_protein
        or fix_nonstandard_residues
        or fix_missing_residues
        or add_missing_hydrogens_pH is not None
        or remove_hetero
        or remove_water
    ):
        # Fix the PDB file
        step2_pdb = fix_pdb_file(
            step1_pdb,
            output_dir,
            fix_nonstandard_residues,
            fix_missing_residues,
            add_missing_hydrogens_pH,
            remove_hetero,
            remove_water,
        )
    else:
        step2_pdb = step1_pdb
    # Protonate the protein
    if protonate:
        final_pdb_file = protonate_protein_protoss(step2_pdb, output_dir)
    else:
        final_pdb_file = step2_pdb
    
    if step1_pdb != final_pdb_file:
        step1_pdb.unlink()
    if step2_pdb != final_pdb_file:
        step2_pdb.unlink()

    return final_pdb_file
