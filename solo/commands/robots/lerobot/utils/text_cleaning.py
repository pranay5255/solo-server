"""
Text cleaning utilities for LeRobot
Handles ANSI escape codes, repo ID cleaning, and unique ID generation
"""

import os
import glob
import re
import time


def clean_ansi_codes(text: str) -> str:
    """
    Remove ANSI escape codes and clean problematic characters from text to prevent file system errors.
    """
    if not text:
        return text
    
    # Remove ANSI escape codes
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    cleaned = ansi_escape.sub('', text)
    
    # Remove backslashes and other problematic characters for file paths
    cleaned = cleaned.replace('\\', '')
    
    # Remove any remaining control characters
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
    
    # Strip whitespace and ensure it's not empty
    cleaned = cleaned.strip()
    
    # If empty after cleaning, provide a safe default
    if not cleaned:
        cleaned = f"dataset_{int(time.time())}"
    
    return cleaned


def clean_repo_id(repo_id: str) -> str:
    """
    Clean repository ID to be HuggingFace Hub compatible.
    """
    if not repo_id:
        return repo_id
    
    # First clean ANSI codes and basic issues
    cleaned = clean_ansi_codes(repo_id)
    
    # Remove leading slashes
    if cleaned.startswith('/'):
        cleaned = cleaned.lstrip('/')
    
    # Remove trailing slashes
    if cleaned.endswith('/'):
        cleaned = cleaned.rstrip('/')
    
    # Ensure it's not empty
    if not cleaned:
        cleaned = f"repo_{int(time.time())}"
    
    return cleaned


def generate_unique_repo_id(base_repo_id: str) -> str:
    """
    Generate a unique repo_id by checking for existing directories and incrementing.
    Looks for existing directories matching the pattern and finds the next available number.
    """
    # Check in the HuggingFace cache directory where LeRobot datasets are stored
    cache_dir = os.path.expanduser("~/.cache/huggingface/lerobot/local")
    
    # Look for existing directories matching the pattern
    pattern = f"{base_repo_id}_*"
    existing_dirs = glob.glob(os.path.join(cache_dir, pattern))
    
    # Extract numbers from existing directories
    numbers = []
    for dir_path in existing_dirs:
        dir_name = os.path.basename(dir_path)
        if dir_name.startswith(base_repo_id + "_"):
            try:
                # Extract the number after the underscore
                number_part = dir_name[len(base_repo_id) + 1:]  # Remove base_repo_id + "_"
                if number_part.isdigit():
                    numbers.append(int(number_part))
            except (ValueError, IndexError):
                continue
    
    # Find the next available number
    if not numbers:
        next_number = 1
    else:
        next_number = max(numbers) + 1
    
    return f"{base_repo_id}_{next_number}"

