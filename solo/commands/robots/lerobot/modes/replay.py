"""
Replay mode for LeRobot
Handles replaying recorded dataset episodes on the robot
"""

import time
import typer
from rich.prompt import Prompt

from solo.commands.robots.lerobot.config import (
    validate_lerobot_config,
    get_robot_config_classes,
    get_known_ids,
    save_lerobot_config,
    is_bimanual_robot,
    is_realman_robot,
    create_follower_config,
    create_bimanual_follower_config,
)
from solo.commands.robots.lerobot.mode_config import use_preconfigured_args, load_mode_config
from solo.commands.robots.lerobot.ports import detect_arm_port, detect_bimanual_arm_ports
from solo.commands.robots.lerobot.utils.text_cleaning import clean_ansi_codes


def replay_mode(config: dict, auto_use: bool = False, replay_options: dict = None):
    """Handle LeRobot replay mode - replay actions from a recorded dataset episode"""
    typer.echo("🔄 Starting LeRobot replay mode...")
    
    # Check if CLI arguments were provided (non-interactive mode)
    if replay_options and replay_options.get('dataset'):
        # Use CLI arguments
        _, follower_port, _, _, robot_type = validate_lerobot_config(config)
        follower_id = replay_options.get('follower_id')
        dataset_repo_id = replay_options.get('dataset')
        episode = replay_options.get('episode', 0)
        fps = replay_options.get('fps', 30)
        play_sounds = True
        
        typer.echo(f"📦 Dataset: {dataset_repo_id}")
        typer.echo(f"📹 Episode: {episode}")
        if follower_id:
            typer.echo(f"🤖 Follower ID: {follower_id}")
    else:
        # Check for preconfigured replay settings
        preconfigured, detected_robot_type = use_preconfigured_args(config, 'replay', 'Replay', auto_use=auto_use)
        
        if preconfigured and preconfigured.get('follower_port') and preconfigured.get('dataset_repo_id'):
            robot_type = preconfigured.get('robot_type')
            follower_port = preconfigured.get('follower_port')
            follower_id = preconfigured.get('follower_id')
            dataset_repo_id = clean_ansi_codes(preconfigured.get('dataset_repo_id', ''))
            episode = preconfigured.get('episode', 0)
            fps = preconfigured.get('fps', 30)
            play_sounds = preconfigured.get('play_sounds', True)
        else:
            # Get robot config
            _, follower_port, _, _, saved_robot_type = validate_lerobot_config(config)
            
            # Use detected robot type if available (e.g., from mismatch detection), otherwise use saved
            robot_type = detected_robot_type if detected_robot_type else saved_robot_type
        
            if not robot_type:
                # Try auto-detection first
                typer.echo("\n🔍 Auto-detecting robot type...")
                try:
                    from solo.commands.robots.lerobot.scan import auto_detect_robot_type
                    detected_type, port_info = auto_detect_robot_type(verbose=True)
                    
                    if detected_type:
                        typer.echo(f"\n🤖 Auto-detected robot type: {detected_type.upper()}")
                        use_detected = Confirm.ask("Use this robot type?", default=True)
                        if use_detected:
                            robot_type = detected_type
                        else:
                            detected_type = None
                    
                    if not detected_type:
                        typer.echo("\n🤖 Select your robot type:")
                        typer.echo("1. SO100 (single arm)")
                        typer.echo("2. SO101 (single arm)")
                        typer.echo("3. Koch (single arm)")
                        typer.echo("4. RealMan R1D2 (follower with SO101 leader)")
                        typer.echo("5. Bimanual SO100")
                        typer.echo("6. Bimanual SO101")
                        robot_choice = int(Prompt.ask("Enter robot type", default="2"))
                        robot_type_map = {
                            1: "so100",
                            2: "so101",
                            3: "koch",
                            4: "realman_r1d2",
                            5: "bi_so100",
                            6: "bi_so101"
                        }
                        robot_type = robot_type_map.get(robot_choice, "so101")
                except Exception as e:
                    typer.echo(f"⚠️  Auto-detection failed: {e}")
                    typer.echo("\n🤖 Select your robot type:")
                    typer.echo("1. SO100 (single arm)")
                    typer.echo("2. SO101 (single arm)")
                    typer.echo("3. Koch (single arm)")
                    typer.echo("4. RealMan R1D2 (follower with SO101 leader)")
                    typer.echo("5. Bimanual SO100")
                    typer.echo("6. Bimanual SO101")
                    robot_choice = int(Prompt.ask("Enter robot type", default="2"))
                    robot_type_map = {
                        1: "so100",
                        2: "so101",
                        3: "koch",
                        4: "realman_r1d2",
                        5: "bi_so100",
                        6: "bi_so101"
                    }
                    robot_type = robot_type_map.get(robot_choice, "so101")
            
            # Handle port detection based on robot type
            if is_realman_robot(robot_type):
                # RealMan: Load network config, no USB port needed
                from solo.commands.robots.lerobot.realman_config import load_realman_config
                lerobot_config = config.get('lerobot', {})
                # Always load fresh config from YAML to pick up changes (like invert_joints)
                realman_config = load_realman_config()
                # Merge with any saved network settings (ip/port) if they exist
                saved_realman = lerobot_config.get('realman_config', {})
                if saved_realman:
                    realman_config['ip'] = saved_realman.get('ip', realman_config['ip'])
                    realman_config['port'] = saved_realman.get('port', realman_config['port'])
                config['realman_config'] = realman_config
                follower_port = None  # Network-based, no USB port
                typer.echo(f"\n🔌 RealMan follower: {realman_config.get('ip')}:{realman_config.get('port')}")
            
            elif is_bimanual_robot(robot_type):
                # Bimanual port detection
                lerobot_config = config.get('lerobot', {})
                left_follower_port = lerobot_config.get('left_follower_port')
                right_follower_port = lerobot_config.get('right_follower_port')
                
                if not left_follower_port or not right_follower_port:
                    left_follower_port, right_follower_port = detect_bimanual_arm_ports("follower")
                    config['left_follower_port'] = left_follower_port
                    config['right_follower_port'] = right_follower_port
            else:
                # Single-arm port detection
                if not follower_port:
                    follower_port, _ = detect_arm_port("follower", robot_type=robot_type)
            
            # Get follower ID
            _, known_follower_ids = get_known_ids(config, robot_type=robot_type)
            from solo.commands.robots.lerobot.config import display_known_ids
            display_known_ids(known_follower_ids, "follower", detected_robot_type=robot_type, config=config)
            default_follower_id = config.get('lerobot', {}).get('follower_id') or f"{robot_type}_follower"
            follower_id = Prompt.ask("Enter follower id", default=default_follower_id)
            
            # Get default dataset from recording config if available
            recording_config = load_mode_config(config, 'recording')
            default_dataset = recording_config.get('dataset_repo_id') if recording_config else None
            
            dataset_repo_id = clean_ansi_codes(Prompt.ask("Enter dataset repository ID", default=default_dataset or ""))
            if '/' not in dataset_repo_id:
                dataset_repo_id = f"local/{dataset_repo_id}"
            
            episode = int(Prompt.ask("Enter episode number to replay", default="0"))
            fps = 30
            play_sounds = True
            
            # Save config
            from solo.commands.robots.lerobot.mode_config import save_replay_config
            save_replay_config(config, {
                'robot_type': robot_type, 'follower_port': follower_port, 'follower_id': follower_id,
                'dataset_repo_id': dataset_repo_id, 'episode': episode, 'fps': fps, 'play_sounds': play_sounds
            })
    
    typer.echo(f"📊 Replaying episode {episode} from {dataset_repo_id}")
    
    # Import lerobot components
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.processor import make_default_robot_action_processor
    from lerobot.robots import make_robot_from_config
    from lerobot.utils.constants import ACTION
    from lerobot.utils.robot_utils import precise_sleep
    from lerobot.utils.utils import log_say
    
    robot = None
    try:
        # Setup robot
        _, follower_config_class = get_robot_config_classes(robot_type)
        if not follower_config_class:
            raise ValueError(f"Unsupported robot type: {robot_type}")
        
        # Create follower config based on robot type
        if is_realman_robot(robot_type):
            # RealMan: Create network-based follower config
            from solo.commands.robots.lerobot.realman_config import create_realman_follower_config
            realman_cfg = config.get('realman_config')
            follower_config = create_realman_follower_config(
                realman_cfg,
                camera_config=None,
                follower_id=follower_id
            )
        
        elif is_bimanual_robot(robot_type):
            lerobot_config = config.get('lerobot', {})
            left_follower_port = lerobot_config.get('left_follower_port')
            right_follower_port = lerobot_config.get('right_follower_port')
            
            follower_config = create_bimanual_follower_config(
                follower_config_class,
                left_follower_port,
                right_follower_port,
                robot_type,
                camera_config=None,
                follower_id=follower_id
            )
        else:
            follower_config = create_follower_config(
                follower_config_class,
                follower_port,
                robot_type,
                follower_id=follower_id
            )
        
        # Load dataset
        dataset = LeRobotDataset(dataset_repo_id, episodes=[episode])
        episode_frames = dataset.hf_dataset.filter(lambda x: x["episode_index"] == episode)
        actions = episode_frames.select_columns(ACTION)
        typer.echo(f"📥 Loaded {len(episode_frames)} frames")
        
        # Connect and replay with retry logic
        robot_action_processor = make_default_robot_action_processor()
        
        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                robot = make_robot_from_config(follower_config)
                robot.connect()
                
                log_say("Replaying episode", play_sounds, blocking=True)
                
                for idx in range(len(episode_frames)):
                    start_t = time.perf_counter()
                    
                    action = {name: actions[idx][ACTION][i] for i, name in enumerate(dataset.features[ACTION]["names"])}
                    processed_action = robot_action_processor((action, robot.get_observation()))
                    robot.send_action(processed_action)
                    
                    precise_sleep(1 / fps - (time.perf_counter() - start_t))
                
                robot.disconnect()
                typer.echo(f"✅ Replay completed! ({len(episode_frames)} frames)")
                break  # Success, exit retry loop
                
            except Exception as e:
                error_msg = str(e)
                # Check if it's a port connection error
                if "Could not connect on port" in error_msg or "Make sure you are using the correct port" in error_msg:
                    if attempt < max_retries:
                        typer.echo(f"❌ Connection failed: {error_msg}")
                        typer.echo("🔄 Attempting to detect new port...")
                        
                        # Detect new follower port(s)
                        if is_bimanual_robot(robot_type):
                            left_follower_port, right_follower_port = detect_bimanual_arm_ports("follower")
                            
                            if left_follower_port and right_follower_port:
                                typer.echo(f"✅ Found new follower ports: {left_follower_port}, {right_follower_port}")
                                
                                # Save updated ports to main lerobot config
                                save_lerobot_config(config, {
                                    'left_follower_port': left_follower_port,
                                    'right_follower_port': right_follower_port
                                })
                                
                                # Recreate follower config
                                follower_config = create_bimanual_follower_config(
                                    follower_config_class,
                                    left_follower_port,
                                    right_follower_port,
                                    robot_type,
                                    camera_config=None,
                                    follower_id=follower_id
                                )
                                typer.echo("🔄 Retrying replay with new ports...")
                                continue
                            else:
                                typer.echo("❌ Could not find new ports. Please check connections.")
                                return
                        else:
                            new_follower_port, _ = detect_arm_port("follower", robot_type=robot_type)
                            
                            if new_follower_port and new_follower_port != follower_port:
                                follower_port = new_follower_port
                                typer.echo(f"✅ Found new follower port: {follower_port}")
                                
                                # Save updated port to main lerobot config (shared across all modes)
                                save_lerobot_config(config, {'follower_port': follower_port})
                                
                                # Save updated port to replay config
                                from solo.commands.robots.lerobot.mode_config import save_replay_config
                                save_replay_config(config, {
                                    'robot_type': robot_type, 'follower_port': follower_port, 'follower_id': follower_id,
                                    'dataset_repo_id': dataset_repo_id, 'episode': episode, 'fps': fps, 'play_sounds': play_sounds
                                })
                                
                                follower_config = create_follower_config(follower_config_class, follower_port, robot_type, follower_id=follower_id)
                                typer.echo("🔄 Retrying replay with new port...")
                                continue
                            else:
                                typer.echo("❌ Could not find new port. Please check connections.")
                                return
                    else:
                        typer.echo(f"❌ Replay failed after retry: {error_msg}")
                        return
                else:
                    raise  # Re-raise non-port errors
        
    except KeyboardInterrupt:
        typer.echo("\n🛑 Stopped by user.")
    except Exception as e:
        typer.echo(f"❌ Replay failed: {e}")
    finally:
        if robot:
            try:
                robot.disconnect()
            except Exception:
                pass

