import os
import sys
from pathlib import Path

# Search for 'DockM8' in parent directories
scripts_path = next((p / "scripts" for p in Path(__file__).resolve().parents if (p / "scripts").is_dir()), None)
dockm8_path = scripts_path.parent
sys.path.append(str(dockm8_path))

from scripts.pocket_finding.utils import get_ligand_coordinates
from scripts.utilities.utilities import load_molecule, printlog


def find_pocket_default(ligand_file: Path, protein_file: Path, radius: int):
	"""
    Extracts the pocket from a protein file using a reference ligand.

    Args:
        ligand_file (Path): The path to the reference ligand file in mol format.
        protein_file (Path): The path to the protein file in pdb format.
        radius (int): The radius of the pocket to be extracted.

    Returns:
        dict: A dictionary containing the coordinates and size of the extracted pocket.
            The dictionary has the following structure:
            {
                "center": [center_x, center_y, center_z],
                "size": [size_x, size_y, size_z]
            }
    """
	printlog(f"Extracting pocket from {protein_file.stem} using {ligand_file.stem} as reference ligand")
	# Load the reference ligand molecule
	ligand_mol = load_molecule(str(ligand_file))
	# Calculate the center coordinates of the pocket
	ligu = get_ligand_coordinates(ligand_mol)
	center_x = ligu["x_coord"].mean().round(2)
	center_y = ligu["y_coord"].mean().round(2)
	center_z = ligu["z_coord"].mean().round(2)
	# Create a dictionary with the pocket coordinates and size
	pocket_coordinates = {
		"center": [center_x, center_y, center_z], "size": [float(radius) * 2, float(radius) * 2, float(radius) * 2], }
	return pocket_coordinates
