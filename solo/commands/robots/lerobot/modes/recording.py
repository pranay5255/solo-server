"""
Recording mode for LeRobot
Handles data collection and recording of robot demonstrations
"""

import typer
from rich.prompt import Prompt, Confirm

from solo.commands.robots.lerobot.config import (
    validate_lerobot_config,
    get_known_ids,
    is_bimanual_robot,
    is_realman_robot,
)
from solo.commands.robots.lerobot.auth import authenticate_huggingface
from solo.commands.robots.lerobot.dataset import handle_existing_dataset, normalize_repo_id
from solo.commands.robots.lerobot.cameras import setup_cameras
from solo.commands.robots.lerobot.mode_config import use_preconfigured_args
from solo.commands.robots.lerobot.ports import detect_arm_port, detect_and_retry_ports, detect_bimanual_arm_ports
from solo.commands.robots.lerobot.utils.text_cleaning import clean_ansi_codes
from solo.commands.robots.lerobot.utils.record_config import unified_record_config


def recording_mode(config: dict, auto_use: bool = False):
    """Handle LeRobot recording mode"""
    typer.echo("🎬 Starting LeRobot recording mode...")
    
    # Check for preconfigured recording settings
    preconfigured = use_preconfigured_args(config, 'recording', 'Recording', auto_use=auto_use)
    
    # Initialize variables
    leader_id = None
    follower_id = None
    
    if preconfigured:
        # Use preconfigured settings
        robot_type = preconfigured.get('robot_type')
        leader_port = preconfigured.get('leader_port')
        follower_port = preconfigured.get('follower_port')
        camera_config = preconfigured.get('camera_config')
        leader_id = preconfigured.get('leader_id')
        follower_id = preconfigured.get('follower_id')
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
        task_description = preconfigured.get('task_description')
        episode_time = preconfigured.get('episode_time')
        num_episodes = preconfigured.get('num_episodes')
        fps = preconfigured.get('fps')
        push_to_hub = preconfigured.get('push_to_hub')
        # When using preconfigured settings, default to resume mode
        should_resume = True
        
        # Validate that we have the required settings
        # RealMan robots don't need follower_port (use network instead)
        if is_realman_robot(robot_type):
            realman_config = preconfigured.get('realman_config')
            if not (leader_port and robot_type and realman_config):
                typer.echo("❌ Preconfigured settings missing required RealMan configuration")
                typer.echo("Please run setup first or use new settings")
                preconfigured = None
        elif not (leader_port and follower_port and robot_type):
            typer.echo("❌ Preconfigured settings missing required robot configuration")
            typer.echo("Please run calibration first or use new settings")
            preconfigured = None
    
    if not preconfigured:
        # Validate configuration using utility function
        leader_port, follower_port, leader_calibrated, follower_calibrated, robot_type = validate_lerobot_config(config)
        
        if not robot_type:
            # Ask for robot type
            typer.echo("\n🤖 Select your robot type:")
            typer.echo("1. SO100 (single arm)")
            typer.echo("2. SO101 (single arm)")
            typer.echo("3. Koch (single arm)")
            typer.echo("4. RealMan R1D2 (follower with SO101 leader)")
            typer.echo("5. Bimanual SO100")
            typer.echo("6. Bimanual SO101")
            robot_choice = int(Prompt.ask("Enter robot type", default="1"))
            robot_type_map = {
                1: "so100",
                2: "so101",
                3: "koch",
                4: "realman_r1d2",
                5: "bi_so100",
                6: "bi_so101"
            }
            robot_type = robot_type_map.get(robot_choice, "so100")
            config['robot_type'] = robot_type
        
        # Handle port/connection detection based on robot type
        if is_realman_robot(robot_type):
            # RealMan: SO101 leader (USB) + RealMan follower (network)
            lerobot_config = config.get('lerobot', {})
            
            # Detect leader port (SO101 USB)
            if not leader_port:
                leader_port = detect_arm_port("leader", robot_type="so101")
                config['leader_port'] = leader_port
            
            # Load RealMan follower config (network)
            from solo.commands.robots.lerobot.realman_config import load_realman_config
            realman_config = lerobot_config.get('realman_config') or load_realman_config()
            config['realman_config'] = realman_config
            
            # For RealMan, follower_port is not used
            follower_port = None
            
            typer.echo(f"\n🔌 Connection Configuration:")
            typer.echo(f"   • Leader (SO101): {leader_port}")
            typer.echo(f"   • Follower (RealMan): {realman_config.get('ip')}:{realman_config.get('port')}")
        
        elif is_bimanual_robot(robot_type):
            # Bimanual port detection
            lerobot_config = config.get('lerobot', {})
            left_leader_port = lerobot_config.get('left_leader_port')
            right_leader_port = lerobot_config.get('right_leader_port')
            left_follower_port = lerobot_config.get('left_follower_port')
            right_follower_port = lerobot_config.get('right_follower_port')
            
            if not left_leader_port or not right_leader_port:
                left_leader_port, right_leader_port = detect_bimanual_arm_ports("leader")
                config['left_leader_port'] = left_leader_port
                config['right_leader_port'] = right_leader_port
            if not left_follower_port or not right_follower_port:
                left_follower_port, right_follower_port = detect_bimanual_arm_ports("follower")
                config['left_follower_port'] = left_follower_port
                config['right_follower_port'] = right_follower_port
        else:
            # Single-arm port detection
            if not leader_port:
                leader_port = detect_arm_port("leader")
                config['leader_port'] = leader_port
            if not follower_port:
                follower_port = detect_arm_port("follower")
                config['follower_port'] = follower_port
        
        # Select ids
        known_leader_ids, known_follower_ids = get_known_ids(config)
        default_leader_id = config.get('lerobot', {}).get('leader_id') or f"{robot_type}_leader"
        default_follower_id = config.get('lerobot', {}).get('follower_id') or f"{robot_type}_follower"
        if known_leader_ids:
            typer.echo("📇 Known leader ids:")
            for i, kid in enumerate(known_leader_ids, 1):
                typer.echo(f"   {i}. {kid}")
        leader_id = Prompt.ask("Enter leader id", default=default_leader_id)
        if known_follower_ids:
            typer.echo("📇 Known follower ids:")
            for i, kid in enumerate(known_follower_ids, 1):
                typer.echo(f"   {i}. {kid}")
        follower_id = Prompt.ask("Enter follower id", default=default_follower_id)

        # Step 1: HuggingFace authentication (optional)
        typer.echo("\n📋 Step 1: HuggingFace Hub Configuration")
        push_to_hub = Confirm.ask("Would you like to push the recorded data to HuggingFace Hub?", default=False)
        hf_username = None
        
        if push_to_hub:
            login_success, hf_username = authenticate_huggingface()
            
            if not login_success:
                typer.echo("❌ HuggingFace authentication failed. Continuing in local-only mode.")
                push_to_hub = False
                hf_username = None  # Clear username for local-only mode
        
        # Step 2: Get recording parameters
        typer.echo("\n⚙️ Step 2: Recording Configuration")
        
        # Get dataset name and handle existing datasets
        dataset_name = Prompt.ask("Enter dataset repository name", default="lerobot-dataset")
        # Only use HuggingFace username if we're actually pushing to hub
        username_for_format = hf_username if push_to_hub else None
        initial_repo_id = normalize_repo_id(dataset_name, hf_username=username_for_format)
        # Check if dataset exists and handle appropriately
        dataset_repo_id, should_resume = handle_existing_dataset(initial_repo_id)
        # Ensure the returned id still has a namespace (user may have typed name-only)
        dataset_repo_id = normalize_repo_id(dataset_repo_id, hf_username=username_for_format)
        # Clean ANSI escape codes to prevent file system errors
        dataset_repo_id = clean_ansi_codes(dataset_repo_id)
        
        # Additional validation: Ensure dataset_repo_id doesn't start with '/' or contain problematic characters
        if dataset_repo_id.startswith('/'):
            typer.echo(f"⚠️  Warning: dataset_repo_id starts with '/', removing it")
            dataset_repo_id = dataset_repo_id.lstrip('/')
        
        # Ensure dataset_repo_id has proper format (owner/name or local/name)
        if '/' not in dataset_repo_id:
            if push_to_hub and hf_username:
                # Use HuggingFace username format for hub uploads
                dataset_repo_id = f"{hf_username}/{dataset_repo_id}"
                typer.echo(f"🔧 Fixed dataset_repo_id format: '{dataset_repo_id}'")
            else:
                # Use local format for local-only datasets
                dataset_repo_id = f"local/{dataset_repo_id}"
                typer.echo(f"🔧 Fixed dataset_repo_id format: '{dataset_repo_id}'")
        
        # Force local format when not pushing to hub
        if not push_to_hub and not dataset_repo_id.startswith('local/'):
            typer.echo(f"⚠️  Not pushing to hub - converting '{dataset_repo_id}' to local format")
            dataset_name_only = dataset_repo_id.split('/')[-1]
            dataset_repo_id = f"local/{dataset_name_only}"
            typer.echo(f"🔧 Using local dataset: '{dataset_repo_id}'")
        
        # Get task description
        task_description = Prompt.ask("Enter task description (e.g., 'Pick up the red cube and place it in the box')")
        
        # Get episode time
        episode_time = float(Prompt.ask("Duration of each recording episode in seconds", default="60"))
        
        # Get number of episodes
        num_episodes = int(Prompt.ask("Total number of episodes to record", default="10"))

        # Setup cameras
        camera_config = setup_cameras()

    # Save configuration before execution (if not using preconfigured settings)
    if not preconfigured:
        from solo.commands.robots.lerobot.mode_config import save_recording_config
        recording_args = {
            'robot_type': robot_type,
            'leader_port': leader_port,
            'follower_port': follower_port,
            'camera_config': camera_config,
            'leader_id': leader_id,
            'follower_id': follower_id,
            'dataset_repo_id': dataset_repo_id,
            'task_description': task_description,
            'episode_time': episode_time,
            'num_episodes': num_episodes,
            'fps': 30,
            'push_to_hub': push_to_hub,
            'should_resume': should_resume
        }
        save_recording_config(config, recording_args)

    # Step 3: Start recording
    typer.echo("\n🎬Starting Data Recording")
    typer.echo("Configuration:")
    typer.echo(f"   • Dataset: {dataset_repo_id}")
    typer.echo(f"   • Task: {task_description}")
    typer.echo(f"   • Episode duration: {episode_time}s")
    typer.echo(f"   • Number of episodes: {num_episodes}")
    typer.echo(f"   • Push to hub: {push_to_hub}")
    typer.echo(f"   • Robot type: {robot_type.upper()}")
    try:
        typer.echo(f"   • Leader id: {leader_id}")
        typer.echo(f"   • Follower id: {follower_id}")
    except NameError:
        pass
    
    # Import lerobot recording components
    from lerobot.scripts.lerobot_record import record
    
    try:
        
        # Create unified record configuration for recording mode
        record_config_kwargs = {
            'robot_type': robot_type,
            'leader_port': leader_port,
            'follower_port': follower_port,
            'camera_config': camera_config,
            'mode': "recording",
            'leader_id': leader_id,
            'follower_id': follower_id,
            'dataset_repo_id': dataset_repo_id,
            'task_description': task_description,
            'episode_time': episode_time,
            'num_episodes': num_episodes,
            'push_to_hub': push_to_hub,
            'fps': 30,
            'should_resume': should_resume,
        }
        
        # Add robot-type specific configuration
        if is_realman_robot(robot_type):
            # Add RealMan network configuration
            realman_config = config.get('realman_config') or config.get('lerobot', {}).get('realman_config')
            record_config_kwargs.update({
                'realman_config': realman_config,
            })
        elif is_bimanual_robot(robot_type):
            # Add bimanual ports
            lerobot_config = config.get('lerobot', {})
            record_config_kwargs.update({
                'left_leader_port': lerobot_config.get('left_leader_port'),
                'right_leader_port': lerobot_config.get('right_leader_port'),
                'left_follower_port': lerobot_config.get('left_follower_port'),
                'right_follower_port': lerobot_config.get('right_follower_port'),
            })
        
        record_config = unified_record_config(**record_config_kwargs)
        
        mode_text = "Resuming" if should_resume else "Starting"
        typer.echo(f"🎬 {mode_text} recording... Follow the on-screen instructions.")
        
        if should_resume:
            typer.echo("📝 Note: Recording will continue from existing dataset")
        
        typer.echo("💡 Tips:")
        typer.echo("   • Move the leader arm to control the follower")
        typer.echo("   • Press Right Arrow (→): Early stop the current episode or reset time and move to the next")
        typer.echo("   • Press Left Arrow (←): Cancel the current episode and re-record it")
        typer.echo("   • Press Escape (ESC): Immediately stop the session, encode videos, and upload the dataset")
        
        # Start recording with retry logic
        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                dataset = record(record_config)
                
                mode_text = "resumed and completed" if should_resume else "completed"
                typer.echo(f"✅ Recording {mode_text}!")
                
                # Get the actual dataset name from the record config for display
                actual_repo_id = record_config.dataset.repo_id
                typer.echo(f"📊 Dataset: {actual_repo_id}")
                typer.echo(f"📈 Total episodes in dataset: {dataset.num_episodes}")
                
                if push_to_hub:
                    typer.echo(f"🚀 Dataset pushed to HuggingFace Hub: https://huggingface.co/datasets/{actual_repo_id}")
                
                break  # Success, exit retry loop
                
            except Exception as e:
                error_msg = str(e)
                # Check if it's a port connection error
                if "Could not connect on port" in error_msg or "Make sure you are using the correct port" in error_msg:
                    if attempt < max_retries:
                        typer.echo(f"❌ Connection failed: {error_msg}")
                        typer.echo("🔄 Attempting to detect new ports...")
                        
                        # Detect new ports and retry
                        new_leader_port, new_follower_port = detect_and_retry_ports(leader_port, follower_port, config)
                        
                        if new_leader_port != leader_port or new_follower_port != follower_port:
                            # Update ports and recreate config
                            leader_port, follower_port = new_leader_port, new_follower_port
                            
                            # Build config kwargs
                            retry_config_kwargs = {
                                'robot_type': robot_type,
                                'leader_port': leader_port,
                                'follower_port': follower_port,
                                'camera_config': camera_config,
                                'mode': "recording",
                                'leader_id': leader_id,
                                'follower_id': follower_id,
                                'dataset_repo_id': dataset_repo_id,
                                'task_description': task_description,
                                'episode_time': episode_time,
                                'num_episodes': num_episodes,
                                'push_to_hub': push_to_hub,
                                'fps': 30,
                                'should_resume': should_resume,
                            }
                            
                            # Add robot-type specific configuration
                            if is_realman_robot(robot_type):
                                # Add RealMan network configuration
                                realman_config = config.get('realman_config') or config.get('lerobot', {}).get('realman_config')
                                retry_config_kwargs.update({
                                    'realman_config': realman_config,
                                })
                            elif is_bimanual_robot(robot_type):
                                # Add bimanual ports
                                lerobot_config = config.get('lerobot', {})
                                retry_config_kwargs.update({
                                    'left_leader_port': lerobot_config.get('left_leader_port'),
                                    'right_leader_port': lerobot_config.get('right_leader_port'),
                                    'left_follower_port': lerobot_config.get('left_follower_port'),
                                    'right_follower_port': lerobot_config.get('right_follower_port'),
                                })
                            
                            record_config = unified_record_config(**retry_config_kwargs)
                            typer.echo("🔄 Retrying recording with new ports...")
                            continue
                        else:
                            typer.echo("❌ Could not find new ports. Please check connections.")
                            return
                    else:
                        typer.echo(f"❌ Recording failed after retry: {error_msg}")
                        return
                elif "Cannot create a file when that file already exists" in error_msg:
                    typer.echo(f"❌ Dataset already exists: {dataset_repo_id}")
                    typer.echo("Please try running the command again.")
                    return
                else:
                    # Non-port related error
                    typer.echo(f"❌ Recording failed: {error_msg}")
                    typer.echo("Please check your robot connections and try again.")
                    return
        
    except KeyboardInterrupt:
        typer.echo("\n🛑 Recording stopped by user.")

