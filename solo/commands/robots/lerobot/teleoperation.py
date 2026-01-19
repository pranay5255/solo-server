"""
Teleoperation utilities for LeRobot
"""

import time
import typer
from rich.prompt import Confirm, Prompt
from typing import Dict, Optional

from solo.commands.robots.lerobot.config import (
    get_robot_config_classes,
    create_follower_config,
    get_known_ids,
    save_lerobot_config,
    is_bimanual_robot,
    create_bimanual_leader_config,
    create_bimanual_follower_config,
)
from solo.commands.robots.lerobot.mode_config import use_preconfigured_args
from solo.commands.robots.lerobot.ports import detect_arm_port, detect_and_retry_ports, detect_bimanual_arm_ports
from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig
from solo.commands.robots.lerobot.config import validate_lerobot_config


# Delay between leader and follower connections (in seconds)
CONNECTION_DELAY_S = 1.0

# Number of connection retries
MAX_CONNECTION_RETRIES = 3


def warm_up_port(port: str, verbose: bool = True) -> bool:
    """
    Warm up the USB connection by doing a few reads before formal connection.
    This helps stabilize timing-sensitive sync_read operations.
    """
    try:
        import dynamixel_sdk as dxl
        
        if verbose:
            typer.echo(f"   🔥 Warming up {port}...")
        
        port_handler = dxl.PortHandler(port)
        packet_handler = dxl.PacketHandler(2.0)
        
        if not port_handler.openPort():
            return False
        
        port_handler.setBaudRate(1_000_000)
        
        # Do a few pings to warm up the connection
        for motor_id in range(1, 7):
            packet_handler.ping(port_handler, motor_id)
        
        # Do a test read of Min_Position_Limit (the problematic operation)
        MIN_POS_ADDR = 52
        for motor_id in range(1, 7):
            for attempt in range(3):
                value, result, _ = packet_handler.read4ByteTxRx(port_handler, motor_id, MIN_POS_ADDR)
                if result == dxl.COMM_SUCCESS:
                    break
                time.sleep(0.05)
        
        port_handler.closePort()
        
        if verbose:
            typer.echo("   ✅ Port warmed up")
        
        # Small delay after closing to let USB settle
        time.sleep(0.2)
        return True
        
    except Exception as e:
        if verbose:
            typer.echo(f"   ⚠️  Warm-up failed: {e}")
        return False


def debug_connect(device, device_name: str, verbose: bool = True):
    """
    Connect a device with detailed step-by-step debugging.
    """
    def log(msg):
        if verbose:
            print(msg, flush=True)
    
    log(f"   📍 Step 1: Connecting bus...")
    
    try:
        device.bus.connect()
        log(f"   ✅ Bus connected")
    except Exception as e:
        log(f"   ❌ Bus connect failed: {e}")
        raise
    
    log(f"   📍 Step 2: Checking calibration...")
    log(f"      Calibration file exists: {device.calibration is not None}")
    
    # Try reading calibration manually with debugging
    try:
        log(f"   📍 Step 2a: Reading Homing_Offset...")
        offsets = device.bus.sync_read("Homing_Offset", normalize=False)
        log(f"      ✅ Homing_Offset: {offsets}")
        time.sleep(0.1)  # Small delay between reads
        
        log(f"   📍 Step 2b: Reading Min_Position_Limit...")
        mins = device.bus.sync_read("Min_Position_Limit", normalize=False)
        log(f"      ✅ Min_Position_Limit: {mins}")
        time.sleep(0.1)
        
        log(f"   📍 Step 2c: Reading Max_Position_Limit...")
        maxes = device.bus.sync_read("Max_Position_Limit", normalize=False)
        log(f"      ✅ Max_Position_Limit: {maxes}")
        time.sleep(0.1)
        
        log(f"   📍 Step 2d: Reading Drive_Mode...")
        drive_modes = device.bus.sync_read("Drive_Mode", normalize=False)
        log(f"      ✅ Drive_Mode: {drive_modes}")
        
        log(f"   ✅ All calibration reads successful")
            
    except Exception as e:
        log(f"   ❌ Calibration read failed: {e}")
        raise
    
    # Now check is_calibrated
    log(f"   📍 Step 3: Checking is_calibrated property...")
    
    try:
        is_cal = device.bus.is_calibrated
        log(f"      is_calibrated: {is_cal}")
    except Exception as e:
        log(f"   ❌ is_calibrated check failed: {e}")
        raise
    
    # Connect cameras if any
    if hasattr(device, 'cameras'):
        log(f"   📍 Step 4: Connecting cameras ({len(device.cameras)} found)...")
        for cam_key, cam in device.cameras.items():
            try:
                cam.connect()
                log(f"      ✅ Camera '{cam_key}' connected")
            except Exception as e:
                log(f"      ❌ Camera '{cam_key}' failed: {e}")
                raise
    
    # Configure
    log(f"   📍 Step 5: Configuring device...")
    
    try:
        device.configure()
        log(f"   ✅ Device configured")
    except Exception as e:
        log(f"   ❌ Configure failed: {e}")
        raise
    
    log(f"   ✅ {device_name} fully connected!")


def teleoperate_with_delay(cfg: TeleoperateConfig, connection_delay: float = CONNECTION_DELAY_S):
    """
    Custom teleoperate function with configurable delay between connections.
    
    This helps avoid timing issues where sync_read fails due to USB contention
    when both arms are connected too quickly.
    """
    import sys
    import logging
    from pprint import pformat
    from dataclasses import asdict
    
    from lerobot.utils.utils import init_logging
    from lerobot.teleoperators import make_teleoperator_from_config
    from lerobot.robots import make_robot_from_config
    from lerobot.processor import make_default_processors
    from lerobot.utils.visualization_utils import init_rerun
    from lerobot.scripts.lerobot_teleoperate import teleop_loop
    
    print("\n" + "="*60, flush=True)
    print("🚀 ENTERING teleoperate_with_delay function", flush=True)
    print("="*60, flush=True)
    
    try:
        import rerun as rr
    except ImportError:
        rr = None
    
    init_logging()
    logging.info(pformat(asdict(cfg)))
    
    if cfg.display_data:
        init_rerun(session_name="teleoperation")
    
    print(f"📍 Leader port: {cfg.teleop.port}", flush=True)
    print(f"📍 Follower port: {cfg.robot.port}", flush=True)
    
    # Create devices
    print("📍 Creating teleop device...", flush=True)
    teleop = make_teleoperator_from_config(cfg.teleop)
    print("📍 Creating robot device...", flush=True)
    robot = make_robot_from_config(cfg.robot)
    print("📍 Creating processors...", flush=True)
    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()
    
    # Warm up both ports before connecting
    print("🔌 Preparing connections...", flush=True)
    leader_port = cfg.teleop.port
    follower_port = cfg.robot.port
    
    warm_up_port(leader_port)
    warm_up_port(follower_port)
    
    # Connect leader with detailed debugging
    typer.echo("🔌 Connecting leader arm...")
    for attempt in range(MAX_CONNECTION_RETRIES):
        try:
            debug_connect(teleop, "Leader", verbose=True)
            break
        except Exception as e:
            if attempt < MAX_CONNECTION_RETRIES - 1:
                typer.echo(f"   ⚠️  Attempt {attempt + 1} failed: {e}")
                typer.echo(f"   🔄 Retrying in {connection_delay}s...")
                # Disconnect bus if it was connected
                if teleop.bus.is_connected:
                    teleop.bus.disconnect()
                time.sleep(connection_delay)
            else:
                raise
    
    # Wait before connecting follower
    if connection_delay > 0:
        typer.echo(f"   ⏳ Waiting {connection_delay}s before connecting follower...")
        time.sleep(connection_delay)
    
    # Connect follower with detailed debugging
    typer.echo("🔌 Connecting follower arm...")
    for attempt in range(MAX_CONNECTION_RETRIES):
        try:
            debug_connect(robot, "Follower", verbose=True)
            break
        except Exception as e:
            if attempt < MAX_CONNECTION_RETRIES - 1:
                typer.echo(f"   ⚠️  Attempt {attempt + 1} failed: {e}")
                typer.echo(f"   🔄 Retrying in {connection_delay}s...")
                # Disconnect bus if it was connected
                if robot.bus.is_connected:
                    robot.bus.disconnect()
                time.sleep(connection_delay)
            else:
                raise
    
    typer.echo("\n🎮 Teleoperation active! Press Ctrl+C to stop.\n")
    
    try:
        teleop_loop(
            teleop=teleop,
            robot=robot,
            fps=cfg.fps,
            display_data=cfg.display_data,
            duration=cfg.teleop_time_s,
            teleop_action_processor=teleop_action_processor,
            robot_action_processor=robot_action_processor,
            robot_observation_processor=robot_observation_processor,
        )
    except KeyboardInterrupt:
        pass
    finally:
        if cfg.display_data and rr is not None:
            rr.rerun_shutdown()
        teleop.disconnect()
        robot.disconnect()

def teleoperation(config: dict = None, auto_use: bool = False) -> bool:
    leader_id = None
    follower_id = None
    camera_config = None

    preconfigured = use_preconfigured_args(config, 'teleop', 'Teleoperation', auto_use=auto_use)
    if preconfigured:
        leader_port = preconfigured.get('leader_port')
        follower_port = preconfigured.get('follower_port')
        robot_type = preconfigured.get('robot_type')
        camera_config = preconfigured.get('camera_config')
        leader_id = preconfigured.get('leader_id')
        follower_id = preconfigured.get('follower_id')
    

    if not preconfigured:
        # Validate configuration using utility function
        leader_port, follower_port, leader_calibrated, follower_calibrated, robot_type = validate_lerobot_config(config)
        
        if not robot_type:
            # Ask for robot type
            typer.echo("\n🤖 Select your robot type:")
            typer.echo("1. SO100 (single arm)")
            typer.echo("2. SO101 (single arm)")
            typer.echo("3. Koch (single arm)")
            typer.echo("4. Bimanual SO100")
            typer.echo("5. Bimanual SO101")
            robot_choice = int(Prompt.ask("Enter robot type", default="1"))
            robot_type_map = {
                1: "so100",
                2: "so101",
                3: "koch",
                4: "bi_so100",
                5: "bi_so101"
            }
            robot_type = robot_type_map.get(robot_choice, "so100")
            config['robot_type'] = robot_type
        
        # Check if bimanual and handle port detection accordingly
        if is_bimanual_robot(robot_type):
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
            if not leader_port:
                leader_port = detect_arm_port("leader", robot_type=robot_type)
                config['leader_port'] = leader_port
            if not follower_port:
                follower_port = detect_arm_port("follower", robot_type=robot_type)
                config['follower_port'] = follower_port
    
        # Prompt/select ids if not provided
        known_leader_ids, known_follower_ids = get_known_ids(config)
        default_leader_id = config.get('lerobot', {}).get('leader_id') or f"{robot_type}_leader"
        default_follower_id = config.get('lerobot', {}).get('follower_id') or f"{robot_type}_follower"

        if not leader_id:
            if known_leader_ids:
                typer.echo("📇 Known leader ids:")
                for i, kid in enumerate(known_leader_ids, 1):
                    typer.echo(f"   {i}. {kid}")
            leader_id = Prompt.ask("Enter leader id", default=default_leader_id)
        if not follower_id:
            if known_follower_ids:
                typer.echo("📇 Known follower ids:")
                for i, kid in enumerate(known_follower_ids, 1):
                    typer.echo(f"   {i}. {kid}")
            follower_id = Prompt.ask("Enter follower id", default=default_follower_id)
        
        # Setup cameras if not provided
        if camera_config is None:
            # Check if cameras were previously configured
            lerobot_config = config.get('lerobot', {})
            prev_camera_config = lerobot_config.get('camera_config', {})
            cameras_previously_enabled = prev_camera_config.get('enabled', False)
            
            # Default to previous setting (no if never configured)
            use_camera = Confirm.ask("Would you like to setup cameras?", default=cameras_previously_enabled)
            if use_camera:
                from solo.commands.robots.lerobot.cameras import setup_cameras
                camera_config = setup_cameras()
            else:
                # Set empty camera config when user chooses not to use cameras
                camera_config = {'enabled': False, 'cameras': []}

    try:
        # Determine config classes based on robot type
        leader_config_class, follower_config_class = get_robot_config_classes(robot_type)
        
        if leader_config_class is None or follower_config_class is None:
            typer.echo(f"❌ Unsupported robot type for teleoperation: {robot_type}")
            return False
        
        # Debug: Show port assignments
        typer.echo(f"\n🔌 Port Configuration:")
        typer.echo(f"   • Leader port:   {leader_port}")
        typer.echo(f"   • Follower port: {follower_port}")
        
        # Create configurations based on whether bimanual or not
        if is_bimanual_robot(robot_type):
            # Create bimanual configurations
            lerobot_config = config.get('lerobot', {})
            left_leader_port = lerobot_config.get('left_leader_port')
            right_leader_port = lerobot_config.get('right_leader_port')
            left_follower_port = lerobot_config.get('left_follower_port')
            right_follower_port = lerobot_config.get('right_follower_port')
            
            leader_config = create_bimanual_leader_config(
                leader_config_class,
                left_leader_port,
                right_leader_port,
                robot_type,
                leader_id=leader_id
            )
            
            follower_config = create_bimanual_follower_config(
                follower_config_class,
                left_follower_port,
                right_follower_port,
                robot_type,
                camera_config,
                follower_id=follower_id
            )
        else:
            # Create single-arm configurations
            leader_config = leader_config_class(port=leader_port, id=leader_id)
            
            # Create robot config with cameras if enabled
            follower_config = create_follower_config(
                follower_config_class,
                follower_port,
                robot_type,
                camera_config,
                follower_id=follower_id,
            )
        
        # Create teleoperation config
        # Using 30 FPS instead of 60 for more stable motor communication
        teleop_config = TeleoperateConfig(
            teleop=leader_config,
            robot=follower_config,
            fps=30,
            display_data=True
        )
        
        # Save configuration before execution (if not using preconfigured settings)
        if config and not preconfigured:
            from .mode_config import save_teleop_config
            if is_bimanual_robot(robot_type):
                # For bimanual, we don't use the standard save_teleop_config
                # Configuration is already saved via save_lerobot_config
                pass
            else:
                save_teleop_config(
                    config,
                    leader_port,
                    follower_port,
                    robot_type,
                    camera_config,
                    leader_id,
                    follower_id,
                )
        
        if is_bimanual_robot(robot_type):
            typer.echo("🎮 Starting bimanual teleoperation... Press Ctrl+C to stop.")
            typer.echo("📋 Move BOTH leader arms to control BOTH follower arms.")
        else:
            typer.echo("🎮 Starting teleoperation... Press Ctrl+C to stop.")
            typer.echo("📋 Move the leader arm to control the follower arm.")
        
        # Start teleoperation with retry logic
        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                # Use our custom teleoperate with delay between connections
                teleoperate_with_delay(teleop_config)
                
                return True
                
            except Exception as e:
                error_msg = str(e)
                
                # Enhanced error reporting for sync_read failures
                if "sync read" in error_msg.lower() or "sync_read" in error_msg.lower():
                    typer.echo(f"\n⚠️  Motor communication error detected!")
                    typer.echo(f"   Error: {error_msg}")
                    typer.echo("")
                    typer.echo("🔍 Running quick diagnostics...")
                    try:
                        from solo.commands.robots.lerobot.scan import diagnose_connection
                        typer.echo(f"\n   Leader port ({leader_port}):")
                        diagnose_connection(leader_port, verbose=True)
                        typer.echo(f"\n   Follower port ({follower_port}):")
                        diagnose_connection(follower_port, verbose=True)
                    except Exception as diag_err:
                        typer.echo(f"   (Diagnostic failed: {diag_err})")
                    typer.echo("")
                    typer.echo("💡 Possible causes:")
                    typer.echo("   1. Motor power issue - check 12V supply")
                    typer.echo("   2. USB timing - try unplugging and waiting 2 seconds")
                    typer.echo("   3. Port swapped - run 'solo robo --scan' to verify")
                    typer.echo("   4. Loose cable in daisy chain")
                    return False
                
                # Check if it's a port connection error
                if "Could not connect on port" in error_msg or "Make sure you are using the correct port" in error_msg:
                    if attempt < max_retries:
                        typer.echo(f"❌ Connection failed: {error_msg}")
                        typer.echo("🔄 Attempting to detect new ports...")
                        
                        # Detect new ports and retry
                        new_leader_port, new_follower_port = detect_and_retry_ports(leader_port, follower_port, config)
                        
                        if new_leader_port != leader_port or new_follower_port != follower_port:
                            # Update ports and recreate configs
                            leader_port, follower_port = new_leader_port, new_follower_port
                            leader_config = leader_config_class(port=leader_port, id=leader_id)
                            follower_config = create_follower_config(
                                follower_config_class,
                                follower_port,
                                robot_type,
                                camera_config,
                                follower_id=follower_id,
                            )
                            teleop_config = TeleoperateConfig(
                                teleop=leader_config,
                                robot=follower_config,
                                fps=60,
                                display_data=True
                            )
                            typer.echo("🔄 Retrying teleoperation with new ports...")
                            continue
                        else:
                            typer.echo("❌ Could not find new ports. Please check connections.")
                            return False
                    else:
                        typer.echo(f"❌ Teleoperation failed after retry: {error_msg}")
                        return False
                else:
                    # Non-port related error
                    typer.echo(f"❌ Teleoperation failed: {error_msg}")
                    return False
        
    except KeyboardInterrupt:
        typer.echo("\n🛑 Teleoperation stopped by user.")
        return True
