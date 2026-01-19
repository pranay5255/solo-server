"""
Training mode for LeRobot
Handles policy training on recorded datasets
"""

import subprocess
import typer
from pathlib import Path
from rich.prompt import Prompt, Confirm

from solo.commands.robots.lerobot.auth import authenticate_huggingface
from solo.commands.robots.lerobot.dataset import check_dataset_exists
from solo.commands.robots.lerobot.mode_config import use_preconfigured_args
from solo.commands.robots.lerobot.utils.text_cleaning import clean_ansi_codes, clean_repo_id


def training_mode(config: dict, auto_use: bool = False):
    """Handle LeRobot training mode"""
    typer.echo("🎓 Starting LeRobot training mode...")
    
    # Check for preconfigured training settings
    preconfigured = use_preconfigured_args(config, 'training', 'Training', auto_use=auto_use)
    training_args = {}
    
    if preconfigured:
        # Use preconfigured settings
        dataset_repo_id = preconfigured.get('dataset_repo_id')
        # Clean ANSI escape codes to prevent file system errors
        if dataset_repo_id:
            dataset_repo_id = clean_ansi_codes(dataset_repo_id)
            
            # Additional validation: Ensure dataset_repo_id doesn't start with '/' or contain problematic characters
            if dataset_repo_id.startswith('/'):
                typer.echo(f"⚠️  Warning: dataset_repo_id starts with '/', removing it")
                dataset_repo_id = dataset_repo_id.lstrip('/')
            
            # Ensure dataset_repo_id has proper format (owner/name or local/name)
            if '/' not in dataset_repo_id:
                dataset_repo_id = f"local/{dataset_repo_id}"
                typer.echo(f"🔧 Fixed dataset_repo_id format: '{dataset_repo_id}'")
        
        output_dir = preconfigured.get('output_dir')
        policy_type = preconfigured.get('policy_type')
        training_args = preconfigured.get('training_args', {})
        
        typer.echo("✅ Using preconfigured training settings")
        
        # Validate that we have the required settings
        if not dataset_repo_id:
            typer.echo("❌ Preconfigured settings missing required dataset configuration")
            typer.echo("Please use new settings")
            preconfigured = None
    
    # Get all configuration parameters
    if preconfigured:
        # Use preconfigured settings (dataset_repo_id already cleaned above)
        output_dir = preconfigured.get('output_dir')
        policy_name = preconfigured.get('policy_type')
        training_steps = training_args.get('training_steps', 20000)
        batch_size = training_args.get('batch_size', 8)
        push_to_hub = training_args.get('push_to_hub', True)
        policy_repo_id = training_args.get('policy_repo_id', "")
        use_wandb = training_args.get('use_wandb', True)
        wandb_project = training_args.get('wandb_project', "lerobot-training")
        
        typer.echo(f"✅ Using preconfigured training parameters:")
        typer.echo(f"   • Training steps: {training_steps}")
        typer.echo(f"   • Batch size: {batch_size}")
        typer.echo(f"   • Output directory: {output_dir}")
        typer.echo(f"   • Push to hub: {push_to_hub}")
        typer.echo(f"   • WandB logging: {use_wandb}")
        if policy_repo_id:
            typer.echo(f"   • Policy repository: {policy_repo_id}")
        if use_wandb:
            typer.echo(f"   • WandB project: {wandb_project}")
    else:
        # Get configuration from user input
        dataset_repo_id = Prompt.ask("Enter dataset repository ID", default="lerobot/svla_so101_pickplace")
        
        # Clean ANSI escape codes to prevent file system errors
        dataset_repo_id = clean_ansi_codes(dataset_repo_id)
        
        # Additional validation: Ensure dataset_repo_id doesn't start with '/' or contain problematic characters
        if dataset_repo_id.startswith('/'):
            typer.echo(f"⚠️  Warning: dataset_repo_id starts with '/', removing it")
            dataset_repo_id = dataset_repo_id.lstrip('/')
        
        # Ensure dataset_repo_id has proper format (owner/name or local/name)
        if '/' not in dataset_repo_id:
            # Check if dataset exists on HuggingFace Hub first
            from solo.commands.robots.lerobot.auth import get_stored_credentials
            stored_username, _ = get_stored_credentials()
            
            if stored_username:
                # Try HuggingFace Hub format first
                hf_repo_id = f"{stored_username}/{dataset_repo_id}"
                typer.echo(f"🔍 Checking for dataset on HuggingFace Hub: {hf_repo_id}")
                
                # Check if dataset exists on hub
                if check_dataset_exists(hf_repo_id):
                    dataset_repo_id = hf_repo_id
                    typer.echo(f"✅ Found dataset on HuggingFace Hub: {dataset_repo_id}")
                else:
                    # Fall back to local format
                    dataset_repo_id = f"local/{dataset_repo_id}"
                    typer.echo(f"🔧 Using local dataset: {dataset_repo_id}")
            else:
                # No username available, use local format
                dataset_repo_id = f"local/{dataset_repo_id}"
                typer.echo(f"🔧 Fixed dataset_repo_id format: '{dataset_repo_id}'")
        
        typer.echo("Select policy type:")
        typer.echo("1. SmolVLA (Vision-Language-Action model)")
        typer.echo("2. ACT (Action Chunking with Transformers)")
        typer.echo("3. PI0 (Policy Iteration Zero)")
        typer.echo("4. TDMPC (Temporal Difference MPC)")
        typer.echo("5. Diffusion Policy (good for most tasks)")
        
        policy_choice = Prompt.ask("Enter policy type", default="1")
        policy_name_map = {
            "1": "smolvla",
            "2": "act", 
            "3": "pi0",
            "4": "tdmpc",
            "5": "diffusion"
        }
        policy_name = policy_name_map[policy_choice]
        
        # Step 2: Training configuration
        typer.echo(f"\n⚙️ Step 2: Training Configuration")
        training_steps = int(Prompt.ask("Number of training steps", default="20000"))
        batch_size = int(Prompt.ask("Batch size", default="8"))
        
        # Output directory with conflict resolution
        default_output_dir = f"outputs/train/{dataset_repo_id.replace('/', '_')}_{policy_name}"
        output_dir = Prompt.ask("Output directory for checkpoints", default=default_output_dir)
        
        # Step 3: Hub pushing configuration
        typer.echo(f"\n🚀 Step 3: HuggingFace Hub Configuration")
        push_to_hub = Confirm.ask("Push trained model to HuggingFace Hub?", default=True)
        policy_repo_id = ""
        hf_username = ""
        
        if push_to_hub:
            # HuggingFace authentication for hub pushing
            typer.echo("\n🔐 HuggingFace Authentication for Model Upload")
            login_success, hf_username = authenticate_huggingface()
            
            if not login_success:
                typer.echo("❌ Cannot push to hub without HuggingFace authentication.")
                push_to_hub = False
            else:
                # Get policy repository ID
                policy_name_clean = policy_name.replace("_", "-")
                dataset_name_clean = dataset_repo_id.split("/")[-1].replace("_", "-")
                
                # Clean the dataset name to remove any problematic characters
                dataset_name_clean = clean_ansi_codes(dataset_name_clean)
                if dataset_name_clean.startswith('/'):
                    dataset_name_clean = dataset_name_clean.lstrip('/')
                
                default_policy_repo = f"{hf_username}/{policy_name_clean}-{dataset_name_clean}"
                
                policy_repo_id = Prompt.ask("Enter policy repo id", default=default_policy_repo)
                
                # Clean the policy repository ID to remove any problematic characters
                policy_repo_id = clean_ansi_codes(policy_repo_id)
                if policy_repo_id.startswith('/'):
                    policy_repo_id = policy_repo_id.lstrip('/')
                    typer.echo(f"🔧 Cleaned policy repo ID: {policy_repo_id}")
        
        # Step 4: WandB logging configuration
        typer.echo(f"\n📊 Step 4: Weights & Biases Configuration")
        use_wandb = Confirm.ask("Enable Weights & Biases logging?", default=True)
        wandb_project = ""
        
        if use_wandb:
            # Login to wandb first
            typer.echo("🔐 Logging into Weights & Biases...")
            try:
                result = subprocess.run(["wandb", "login"], check=False)
                if result.returncode != 0:
                    typer.echo("❌ WandB login failed. Continuing without WandB logging.")
                    use_wandb = False
                else:
                    typer.echo("✅ Successfully logged into WandB")
                    wandb_project = Prompt.ask("WandB project name", default="lerobot-training")
            except FileNotFoundError:
                typer.echo("❌ wandb CLI not found. Please install with: pip install wandb")
                typer.echo("Continuing without WandB logging.")
                use_wandb = False
            except Exception as e:
                typer.echo(f"❌ Error during WandB login: {e}")
                typer.echo("Continuing without WandB logging.")
                use_wandb = False
    
    # Debug: Log the final dataset_repo_id before training
    typer.echo(f"🔍 Debug - Final dataset_repo_id for training: '{dataset_repo_id}'")
    
    # Check if dataset exists locally
    if check_dataset_exists(dataset_repo_id):
        typer.echo(f"✅ Found local dataset: {dataset_repo_id}")
    
    # Handle pretrained policy path
    pretrained_policy_path = training_args.get('pretrained_path')
    if pretrained_policy_path:
        typer.echo(f"✅ Using preconfigured pretrained checkpoint: {pretrained_policy_path}")
    elif policy_name == "smolvla":
        pretrained_policy_path = "lerobot/smolvla_base"
        typer.echo(" ℹ️ Using default pretrained SmolVLA checkpoint: lerobot/smolvla_base")
    else:
        pretrained_policy_path = None
    training_args['pretrained_path'] = pretrained_policy_path
    
    # Check if output directory exists and handle conflicts
    output_path = Path(output_dir)
    resume_training = False
    
    if output_path.exists() and output_path.is_dir():
        typer.echo(f"\n⚠️  Output directory already exists: {output_dir}")
        
        # Check if there are checkpoints (indicating a previous training run)
        checkpoint_files = list(output_path.glob("**/*checkpoint*")) + list(output_path.glob("**/*.pt"))
        has_checkpoints = len(checkpoint_files) > 0
        
        if has_checkpoints:
            typer.echo("📁 Found existing checkpoints in directory.")
            choice = Prompt.ask(
                "What would you like to do?",
                choices=["resume", "overwrite", "new_dir"],
                default="resume"
            )
        else:
            typer.echo("📁 Directory exists.")
            choice = Prompt.ask(
                "What would you like to do?", 
                choices=["overwrite", "new_dir"],
                default="overwrite"
            )
        
        if choice == "resume":
            resume_training = True
            typer.echo("🔄 Will resume training from existing checkpoints")
        elif choice == "overwrite":
            import shutil
            shutil.rmtree(output_path)
            typer.echo("🗑️  Removed existing directory")
        elif choice == "new_dir":
            # Generate a unique directory name
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = f"{output_dir}_{timestamp}"
            output_path = Path(output_dir)  # Update output_path too
            typer.echo(f"📁 Using new directory: {output_dir}")
    else:
        typer.echo(f"✅ Directory ready: {output_dir}")
    
    # Step 5: Start training
    typer.echo(f"\n🎓 Step 5: Starting Training")
    typer.echo("Configuration:")
    typer.echo(f"   • Dataset: {dataset_repo_id}")
    typer.echo(f"   • Policy: {policy_name}")
    typer.echo(f"   • Training steps: {training_steps}")
    typer.echo(f"   • Batch size: {batch_size}")
    typer.echo(f"   • Output directory: {output_dir}")
    typer.echo(f"   • Resume training: {resume_training}")
    typer.echo(f"   • Push to Hub: {push_to_hub}")
    if push_to_hub:
        typer.echo(f"   • Policy repository: {policy_repo_id}")
    typer.echo(f"   • WandB logging: {use_wandb}")
    if use_wandb:
        typer.echo(f"   • WandB project: {wandb_project}")
    
    # Save configuration before execution (if not using preconfigured settings)
    if not preconfigured:
        from solo.commands.robots.lerobot.mode_config import save_training_config
        training_args = {
            'dataset_repo_id': dataset_repo_id,
            'output_dir': output_dir,
            'policy_type': policy_name,
            'pretrained_policy_path': pretrained_policy_path,
            'training_args': {
                'training_steps': training_steps,
                'batch_size': batch_size,
                'push_to_hub': push_to_hub,
                'policy_repo_id': policy_repo_id,
                'use_wandb': use_wandb,
                'wandb_project': wandb_project
            }
        }
        save_training_config(config, training_args)

    # Import lerobot training components
    from lerobot.scripts.lerobot_train import train
    from lerobot.configs.train import TrainPipelineConfig
    from lerobot.configs.default import DatasetConfig, WandBConfig
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.diffusion.configuration_diffusion import DiffusionConfig
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.tdmpc.configuration_tdmpc import TDMPCConfig
    from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
    from lerobot.policies.pi0.configuration_pi0 import PI0Config
    
    # Suppress warnings
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")
    warnings.filterwarnings("ignore", message=".*torch_dtype.*")
    warnings.filterwarnings("ignore", message=".*video decoding.*")
    
    try:
        # Create output directory only if resuming (LeRobot will create it otherwise)
        if resume_training:
            output_path.mkdir(parents=True, exist_ok=True)
        
        # Create dataset config
        dataset_config = DatasetConfig(repo_id=dataset_repo_id)

        # Ensure video decoding backend is available. TorchCodec can be installed without
        # shipping the required FFmpeg shared libraries which causes runtime failures
        # inside the dataloader workers. We proactively fall back to PyAV when
        # TorchCodec cannot be imported.
        if dataset_config.video_backend == "torchcodec":
            try:  # pragma: no cover - best effort guard
                import torchcodec  # noqa: F401
            except Exception as torchcodec_error:
                typer.echo(
                    "⚠️ TorchCodec video backend unavailable ("
                    + str(torchcodec_error)
                    + ") — falling back to PyAV."
                )
                dataset_config.video_backend = "pyav"
        typer.echo(f"   • Video backend: {dataset_config.video_backend}")
        
        # Create policy config based on choice
        if pretrained_policy_path:
            typer.echo(f"📥 Loading pretrained policy config from {pretrained_policy_path}")
            policy_config = PreTrainedConfig.from_pretrained(pretrained_policy_path)
            policy_config.pretrained_path = pretrained_policy_path
            if policy_name and policy_config.type != policy_name:
                typer.echo(
                    f"⚠️ Loaded checkpoint type '{policy_config.type}' does not match selected policy '{policy_name}'."
                )
            policy_name = policy_config.type
        else:
            if policy_name == "diffusion":
                policy_config = DiffusionConfig()
            elif policy_name == "act":
                policy_config = ACTConfig()
            elif policy_name == "tdmpc":
                policy_config = TDMPCConfig()
            elif policy_name == "smolvla":
                policy_config = SmolVLAConfig()
            elif policy_name == "pi0":
                policy_config = PI0Config()
            else:
                raise ValueError(f"Unknown policy type: {policy_name}")
        
        # Set repo_id for hub pushing if configured
        if policy_repo_id:
            # Final cleaning of policy_repo_id before setting
            original_repo_id = policy_repo_id
            policy_repo_id = clean_repo_id(policy_repo_id)
            
            if original_repo_id != policy_repo_id:
                typer.echo(f"🔧 Cleaned policy repo ID: '{original_repo_id}' -> '{policy_repo_id}'")
            
            # Add repo_id as an attribute to the policy config
            policy_config.repo_id = policy_repo_id
            typer.echo(f"🔍 Setting policy repo_id to: '{policy_config.repo_id}'")
        policy_config.push_to_hub = push_to_hub
        
        # Create WandB config
        wandb_config = WandBConfig(
            enable=use_wandb,
            project=wandb_project if use_wandb else None
        )
        
        # Create training config with progress tracking
        train_config = TrainPipelineConfig(
            dataset=dataset_config,
            policy=policy_config,
            output_dir=output_path,
            steps=training_steps,
            batch_size=batch_size,
            save_freq=1000,  # Save checkpoints every 1000 steps
            save_checkpoint=True,
            wandb=wandb_config,
            seed=1000,
            resume=resume_training,  # Use the resume flag we determined above
        )
        
        typer.echo("🎓 Starting training... This may take a while.")
        typer.echo("💡 Tips:")
        typer.echo("   • Training progress will be logged to the console")
        typer.echo(f"   • Checkpoints saved every 1000 steps")
        if use_wandb:
            typer.echo(f"   • Monitor progress at https://wandb.ai/{wandb_project}")
        typer.echo("   • Checkpoints will be saved to the output directory")
        typer.echo("   • Press Ctrl+C to stop training early")
        
        # Add progress tracking
        typer.echo(f"\n📊 Training Progress:")
        typer.echo(f"   • Total steps: {training_steps}")
        typer.echo(f"   • Batch size: {batch_size}")
        typer.echo(f"   • Estimated time: {training_steps * batch_size / 1000:.1f} minutes")
        
        # Start training with progress tracking
        typer.echo(f"\n🚀 Starting training at step 0/{training_steps}...")
        typer.echo("📈 Progress will be shown in the console output below...")
        train(train_config)
        
        typer.echo(f"✅ Training completed!")
        typer.echo(f"📊 Dataset: {dataset_repo_id}")
        typer.echo(f"🤖 Policy: {policy_name}")
        typer.echo(f"💾 Checkpoints saved to: {output_dir}")
        
        if push_to_hub and policy_repo_id:
            typer.echo(f"🚀 Model pushed to HuggingFace Hub: https://huggingface.co/{policy_repo_id}")
        
        if use_wandb:
            typer.echo(f"📈 Training logs: https://wandb.ai/{wandb_project}")
        
        
    except KeyboardInterrupt:
        typer.echo("\n🛑 Training stopped by user.")
        typer.echo("💾 Partial checkpoints may have been saved to the output directory.")
    except Exception as e:
        import traceback
        typer.echo(f"❌ Training failed: {e}")
        typer.echo("\n🔍 Full error traceback:")
        typer.echo(traceback.format_exc())
        typer.echo("Please check your dataset and configuration.")

