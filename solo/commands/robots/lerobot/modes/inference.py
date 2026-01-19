"""
Inference mode for LeRobot
Handles running pretrained policies on the robot
"""

import os
import typer
from rich.prompt import Prompt, Confirm

from solo.commands.robots.lerobot.config import (
    validate_lerobot_config,
    get_known_ids,
)
from solo.commands.robots.lerobot.auth import authenticate_huggingface
from solo.commands.robots.lerobot.cameras import setup_cameras
from solo.commands.robots.lerobot.mode_config import use_preconfigured_args
from solo.commands.robots.lerobot.ports import detect_arm_port, detect_and_retry_ports
from solo.commands.robots.lerobot.utils.record_config import unified_record_config


def inference_mode(config: dict, auto_use: bool = False):
    """Handle LeRobot inference mode"""
    typer.echo("🔮 Starting LeRobot inference mode...")
    
    # Check for preconfigured inference settings
    preconfigured = use_preconfigured_args(config, 'inference', 'Inference', auto_use=auto_use)

    # Initialize variables
    leader_id = None
    follower_id = None
    
    if preconfigured:
        # Use preconfigured settings
        robot_type = preconfigured.get('robot_type')
        leader_port = preconfigured.get('leader_port')
        leader_id = preconfigured.get('leader_id')
        follower_port = preconfigured.get('follower_port')
        follower_id = preconfigured.get('follower_id')
        camera_config = preconfigured.get('camera_config')
        policy_path = preconfigured.get('policy_path')
        task_description = preconfigured.get('task_description')
        inference_time = preconfigured.get('inference_time')
        fps = preconfigured.get('fps')
        use_teleoperation = preconfigured.get('use_teleoperation')
        
        # Get calibration status from config for preconfigured settings
        leader_calibrated = config.get('lerobot', {}).get('leader_calibrated', False)
        follower_calibrated = config.get('lerobot', {}).get('follower_calibrated', False)
        
        typer.echo("✅ Using preconfigured inference settings")
        
        # Validate that we have the required settings
        if not (follower_port and policy_path):
            typer.echo("❌ Preconfigured settings missing required configuration")
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
            robot_choice = int(Prompt.ask("Enter robot type", default="2"))
            robot_type_map = {
                1: "so100",
                2: "so101",
                3: "koch"
            }
            robot_type = robot_type_map.get(robot_choice, "so101")
            config['robot_type'] = robot_type
        if not follower_port:
            follower_port = detect_arm_port("follower")
            config['follower_port'] = follower_port
        
        typer.echo("✅ Found calibrated follower arm:")
        typer.echo(f"   • Robot type: {robot_type.upper()}")
        typer.echo(f"   • Follower arm: {follower_port}")
        
        # Check if leader arm is available for teleoperation
        use_teleoperation = False
        known_leader_ids, known_follower_ids = get_known_ids(config)
        if leader_port and leader_calibrated:
            use_teleoperation = Confirm.ask("Would you like to teleoperate during inference?", default=False)
            if use_teleoperation:
                default_leader_id = config.get('lerobot', {}).get('leader_id') or f"{robot_type}_leader"
                if known_leader_ids:
                    typer.echo("📇 Known leader ids:")
                    for i, kid in enumerate(known_leader_ids, 1):
                        typer.echo(f"   {i}. {kid}")
                leader_id = Prompt.ask("Enter leader id", default=default_leader_id)
                typer.echo("🎮 Teleoperation enabled - you can override the policy using the leader arm")

        default_follower_id = config.get('lerobot', {}).get('follower_id') or f"{robot_type}_follower"
        if known_follower_ids:
            typer.echo("📇 Known follower ids:")
            for i, kid in enumerate(known_follower_ids, 1):
                typer.echo(f"   {i}. {kid}")
        follower_id = Prompt.ask("Enter follower id", default=default_follower_id)
        
        # Step 1: HuggingFace authentication
        typer.echo("\n📋 Step 1: HuggingFace Authentication")
        login_success, hf_username = authenticate_huggingface()
        
        if not login_success:
            typer.echo("❌ Cannot proceed with inference without HuggingFace authentication.")
            typer.echo("💡 HuggingFace authentication is required to download pre-trained models.")
            return
        
        # Step 2: Get policy path
        typer.echo("\n🤖 Step 2: Policy Configuration")
        policy_path = Prompt.ask("Enter policy path (HuggingFace model ID or local path)")
        
        # Step 3: Inference configuration
        typer.echo("\n⚙️ Step 3: Inference Configuration")
        
        # Get inference duration
        inference_time = float(Prompt.ask("Duration of inference session in seconds", default="60"))
        
        # Get task description (optional for some policies)
        task_description = Prompt.ask("Enter task description", default="")

        # Setup cameras
        camera_config = setup_cameras()
        
        # Save configuration 
        from solo.commands.robots.lerobot.mode_config import save_inference_config
        inference_args = {
            'robot_type': robot_type,
            'leader_port': leader_port,
            'leader_id': leader_id,
            'follower_id': follower_id,
            'follower_port': follower_port,
            'camera_config': camera_config,
            'policy_path': policy_path,
            'task_description': task_description,
            'inference_time': inference_time,
            'fps': 30,
            'use_teleoperation': use_teleoperation
        }
        save_inference_config(config, inference_args)
    
    # Import lerobot inference components
    from lerobot.scripts.lerobot_record import record
    
    try:
        # Set up Windows-specific environment variables for HuggingFace Hub
        os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
        typer.echo(f"📥 Loading model: {policy_path}")

        # Step 4: Start inference
        typer.echo("\n🔮 Step 4: Starting Inference")
        typer.echo("Configuration:")
        typer.echo(f"   • Policy: {policy_path}")
        typer.echo(f"   • Inference duration: {inference_time}s")
        typer.echo(f"   • Task: {task_description or 'Not specified'}")
        typer.echo(f"   • Robot type: {robot_type.upper()}")
        typer.echo(f"   • Teleoperation: {'Enabled' if use_teleoperation else 'Disabled'}")
        
        # Create unified record configuration for inference mode
        record_config = unified_record_config(
            robot_type=robot_type,
            leader_port=leader_port,
            leader_id=leader_id,
            follower_id=follower_id,
            follower_port=follower_port,
            camera_config=camera_config,
            mode="inference",
            policy_path=policy_path,
            task_description=task_description,
            inference_time=inference_time,
            fps=30,
            use_teleoperation=use_teleoperation,
        )
        
        typer.echo("✅ Policy and robot configuration loaded successfully!")
        typer.echo("🔮 Starting inference... Follow the robot's movements.")
        typer.echo("💡 Tips:")
        if use_teleoperation:
            typer.echo("   • The robot will execute the policy autonomously")
            typer.echo("   • Move the leader arm to override the policy")
            typer.echo("   • Release the leader arm to let the policy take control")
        else:
            typer.echo("   • The robot will execute the policy autonomously")
        typer.echo("   • Press Right Arrow (→): Early stop the current episode or reset time and move to the next")
        typer.echo("   • Press Left Arrow (←): Cancel the current episode and re-record it")
        typer.echo("   • Press Escape (ESC): Immediately stop the session, encode videos, and upload the dataset")
        
        # Start inference with retry logic
        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                # Start inference using unified record function (without dataset)
                record(record_config)
                
                typer.echo("\n✅ Inference completed successfully!")
                
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
                            record_config = unified_record_config(
                                robot_type=robot_type,
                                leader_port=leader_port,
                                follower_port=follower_port,
                                camera_config=camera_config,
                                mode="inference",
                                policy_path=policy_path,
                                task_description=task_description,
                                inference_time=inference_time,
                                fps=30,
                                use_teleoperation=use_teleoperation,
                            )
                            typer.echo("🔄 Retrying inference with new ports...")
                            continue
                        else:
                            typer.echo("❌ Could not find new ports. Please check connections.")
                            return
                    else:
                        typer.echo(f"❌ Inference failed after retry: {error_msg}")
                        return
                else:
                    # Non-port related error
                    typer.echo(f"❌ Inference failed: {error_msg}")
                    typer.echo("💡 Troubleshooting tips:")
                    typer.echo("   • Check if the model path is correct")
                    typer.echo("   • Ensure you have internet connection for HuggingFace models")
                    typer.echo("   • Verify HuggingFace authentication is working")
                    typer.echo("   • For local paths, ensure the file exists and is accessible")
                    return
        
    except PermissionError as e:
        typer.echo(f"❌ Permission error loading policy: {e}")
        
    except KeyboardInterrupt:
        typer.echo("\n🛑 Inference stopped by user.")

