"""
Dataset utilities for LeRobot
"""

import typer
from pathlib import Path
from typing import Optional, Tuple
from rich.prompt import Prompt, Confirm


def check_dataset_exists(repo_id: str, root: Optional[str] = None) -> bool:
    """
    Check if a dataset already exists and is valid for resuming.
    A valid dataset must have the directory AND the meta/info.json metadata file.
    """
    if root is not None:
        dataset_path = Path(root)
    else:
        # Import
        from lerobot.utils.constants import HF_LEROBOT_HOME
        dataset_path = HF_LEROBOT_HOME / repo_id
    
    if not dataset_path.exists() or not dataset_path.is_dir():
        return False
    
    # Check for required metadata file - lerobot stores info.json in meta/ subdirectory
    info_file = dataset_path / "meta" / "info.json"
    return info_file.exists()


def check_dataset_directory_exists(repo_id: str, root: Optional[str] = None) -> Tuple[bool, Optional[Path]]:
    """
    Check if a dataset directory exists (even if incomplete).
    Returns (exists, path) tuple.
    """
    if root is not None:
        dataset_path = Path(root)
    else:
        from lerobot.utils.constants import HF_LEROBOT_HOME
        dataset_path = HF_LEROBOT_HOME / repo_id
    
    return dataset_path.exists() and dataset_path.is_dir(), dataset_path


def handle_existing_dataset(repo_id: str, root: Optional[str] = None) -> Tuple[str, bool]:
    """
    Handle the case when a dataset already exists
    Returns (final_repo_id, should_resume)
    """
    import shutil
    
    while True:
        # Check if valid dataset exists (has info.json)
        if check_dataset_exists(repo_id, root):
            # Valid dataset exists, ask user what to do
            typer.echo(f"\n⚠️  Dataset already exists: {repo_id}")
            
            choice = Confirm.ask("Resume recording?", default=True)
            
            if choice:
                # User wants to resume
                return repo_id, True
            else:
                # User wants a different name
                typer.echo(f"\nCurrent repository: {repo_id}")
                repo_id = Prompt.ask("Enter a new repository ID", default=repo_id)
                continue
        
        # Check if directory exists but is incomplete (no info.json)
        dir_exists, dataset_path = check_dataset_directory_exists(repo_id, root)
        
        if dir_exists:
            # Directory exists but dataset is incomplete
            typer.echo(f"\n⚠️  Incomplete dataset directory found: {dataset_path}")
            typer.echo("   This directory exists but is missing required metadata (info.json).")
            typer.echo("   This usually happens when a previous recording attempt failed.\n")
            
            typer.echo("Options:")
            typer.echo("  1. Delete the incomplete directory and start fresh")
            typer.echo("  2. Choose a different dataset name")
            
            choice = Prompt.ask("Select option", choices=["1", "2"], default="1")
            
            if choice == "1":
                # User wants to delete and start fresh
                confirm_delete = Confirm.ask(
                    f"Are you sure you want to delete '{dataset_path}'?", 
                    default=False
                )
                if confirm_delete:
                    try:
                        shutil.rmtree(dataset_path)
                        typer.echo(f"✅ Deleted incomplete dataset directory")
                        return repo_id, False
                    except Exception as e:
                        typer.echo(f"❌ Failed to delete directory: {e}")
                        typer.echo("Please delete it manually or choose a different name.")
                        repo_id = Prompt.ask("Enter a new repository ID", default=repo_id)
                else:
                    # User cancelled delete, ask for new name
                    repo_id = Prompt.ask("Enter a new repository ID", default=repo_id)
            else:
                # User wants a different name
                repo_id = Prompt.ask("Enter a new repository ID", default=repo_id)
            continue
        
        # No directory exists at all, we can proceed with creation
        return repo_id, False


def normalize_repo_id(repo_id: str, hf_username: Optional[str] = None) -> str:
    """
    Ensure repo_id follows the expected 'owner/name' format used by LeRobot.
    If no owner namespace is provided, default to:
      - '{hf_username}/<name>' when a HuggingFace username is known
      - 'local/<name>' otherwise (purely local namespace)
    """
    if "/" in repo_id and len(repo_id.split("/")) == 2:
        return repo_id
    name_only = repo_id.split("/")[-1].strip()
    if hf_username:
        owner = hf_username.strip()
        if owner:
            return f"{owner}/{name_only}"
    return f"local/{name_only}"
