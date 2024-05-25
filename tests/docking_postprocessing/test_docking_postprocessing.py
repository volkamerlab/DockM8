import pytest
import os
import sys
from pathlib import Path

from rdkit.Chem import PandasTools

# Search for 'DockM8' in parent directories
tests_path = next((p / "tests" for p in Path(__file__).resolve().parents if (p / "tests").is_dir()), None)
dockm8_path = tests_path.parent
sys.path.append(str(dockm8_path))

from scripts.docking_postprocessing.docking_postprocessing import docking_postprocessing


@pytest.fixture
def common_test_data():
	"""Set up common test data."""
	dockm8_path = next((p / "tests" for p in Path(__file__).resolve().parents if (p / "tests").is_dir()), None).parent
	input_sdf = Path(dockm8_path / "tests/test_files/docking_postprocessing/example_poses_1fvv.sdf")
	output_path = Path(dockm8_path / "tests/test_files/docking_postprocessing/example_poses_1fvv_postprocessed.sdf")
	protein_file = Path(dockm8_path / "tests/test_files/docking_postprocessing/example_prepared_receptor_1fvv.pdb")
	n_cpus = int(os.cpu_count() * 0.9)
	return input_sdf, output_path, protein_file, n_cpus


@pytest.fixture
def cleanup(request):
	"""Cleanup fixture to remove generated files after each test."""
	output_dir = dockm8_path / "tests/test_files/docking_postprocessing/"

	def remove_created_files():
		for file in output_dir.iterdir():
			if file.name in ["example_poses_1fvv_postprocessed.sdf"]:
				file.unlink()

	request.addfinalizer(remove_created_files)


def test_docking_postprocessing(common_test_data, cleanup):
	"""
    Test case for docking_postprocessing function.

    Args:
        common_test_data: A tuple containing the input_sdf, output_path, protein_file, bust_poses, strain_cutoff, clash_cutoff, and n_cpus.

    Returns:
        None
    """
	input_sdf, output_path, protein_file, n_cpus = common_test_data
	minimize_poses = True
	bust_poses = True
	strain_cutoff = 5
	clash_cutoff = 3
	classy_pose = False
	classy_pose_model = None
	result = docking_postprocessing(input_sdf,
									output_path,
									protein_file,
									minimize_poses,
									bust_poses,
									strain_cutoff,
									clash_cutoff,
									classy_pose,
									classy_pose_model,
									n_cpus)
	assert result == output_path
	assert output_path.exists()
	output_data = PandasTools.LoadSDF(str(output_path))
	assert len(output_data) == 14


def test_docking_postprocessing_without_pose_busting(common_test_data, cleanup):
	"""
    Test case for docking_postprocessing function without pose busting.

    Args:
        common_test_data: A tuple containing the input_sdf, output_path, protein_file, bust_poses, strain_cutoff, clash_cutoff, and n_cpus.

    Returns:
        None
    """
	input_sdf, output_path, protein_file, n_cpus = common_test_data
	minimize_poses = False
	bust_poses = False
	strain_cutoff = 5
	clash_cutoff = 3
	classy_pose = False
	classy_pose_model = None
	result = docking_postprocessing(input_sdf,
									output_path,
									protein_file,
									minimize_poses,
									bust_poses,
									strain_cutoff,
									clash_cutoff,
									classy_pose,
									classy_pose_model,
									n_cpus)
	assert result == output_path
	assert output_path.exists()
	output_data = PandasTools.LoadSDF(str(output_path))
	assert len(output_data) == 14


def test_docking_postprocessing_with_no_cutoffs(common_test_data, cleanup):
	"""
    Test case for docking_postprocessing function with no strain or clash cutoffs.

    Args:
        common_test_data: A tuple containing the input_sdf, output_path, protein_file, bust_poses, strain_cutoff, clash_cutoff, and n_cpus.

    Returns:
        None
    """
	input_sdf, output_path, protein_file, n_cpus = common_test_data
	minimize_poses = False
	bust_poses = True
	strain_cutoff = None
	clash_cutoff = None
	classy_pose = False
	classy_pose_model = None
	result = docking_postprocessing(input_sdf,
									output_path,
									protein_file,
									minimize_poses,
									bust_poses,
									strain_cutoff,
									clash_cutoff,
									classy_pose,
									classy_pose_model,
									n_cpus)
	assert result == output_path
	assert output_path.exists()
	output_data = PandasTools.LoadSDF(str(output_path))
	assert len(output_data) == 40


def test_docking_postprocessing_minimization(common_test_data, cleanup):
	"""
    Test case for docking_postprocessing function with minimization.

    Args:
        common_test_data: A tuple containing the input_sdf, output_path, protein_file, bust_poses, strain_cutoff, clash_cutoff, and n_cpus.

    Returns:
        None
    """
	input_sdf, output_path, protein_file, n_cpus = common_test_data
	minimize_poses = True
	bust_poses = True
	strain_cutoff = None
	clash_cutoff = None
	classy_pose = False
	classy_pose_model = None
	result = docking_postprocessing(input_sdf,
									output_path,
									protein_file,
									minimize_poses,
									bust_poses,
									strain_cutoff,
									clash_cutoff,
									classy_pose,
									classy_pose_model,
									n_cpus)
	assert result == output_path
	assert output_path.exists()
	output_data = PandasTools.LoadSDF(str(output_path))
	assert len(output_data) == 40


def test_docking_postprocessing_classy_pose_SVM(common_test_data, cleanup):
	"""
    Test case for docking_postprocessing function with minimization.

    Args:
        common_test_data: A tuple containing the input_sdf, output_path, protein_file, bust_poses, strain_cutoff, clash_cutoff, and n_cpus.

    Returns:
        None
    """
	input_sdf, output_path, protein_file, n_cpus = common_test_data
	minimize_poses = False
	bust_poses = False
	strain_cutoff = None
	clash_cutoff = None
	classy_pose = True
	classy_pose_model = 'SVM'
	result = docking_postprocessing(input_sdf,
									output_path,
									protein_file,
									minimize_poses,
									bust_poses,
									strain_cutoff,
									clash_cutoff,
									classy_pose,
									classy_pose_model,
									n_cpus)
	assert result == output_path
	assert output_path.exists()
	output_data = PandasTools.LoadSDF(str(output_path))
	assert len(output_data) == 2


def test_docking_postprocessing_classy_pose_LGBM(common_test_data, cleanup):
	"""
    Test case for docking_postprocessing function with minimization.

    Args:
        common_test_data: A tuple containing the input_sdf, output_path, protein_file, bust_poses, strain_cutoff, clash_cutoff, and n_cpus.

    Returns:
        None
    """
	input_sdf, output_path, protein_file, n_cpus = common_test_data
	minimize_poses = False
	bust_poses = False
	strain_cutoff = None
	clash_cutoff = None
	classy_pose = True
	classy_pose_model = 'LGBM'
	result = docking_postprocessing(input_sdf,
									output_path,
									protein_file,
									minimize_poses,
									bust_poses,
									strain_cutoff,
									clash_cutoff,
									classy_pose,
									classy_pose_model,
									n_cpus)
	assert result == output_path
	assert output_path.exists()
	output_data = PandasTools.LoadSDF(str(output_path))
	assert len(output_data) == 0
