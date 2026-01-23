"""
RealMan-specific configuration utilities for Solo CLI

Handles loading and creating RealMan robot configurations for integration
with the LeRobot framework. RealMan robots (R1D2, RM65, RM75, etc.) connect
via network (IP/port) rather than USB serial.

The typical setup uses:
- SO101 as the leader arm (USB serial)
- RealMan R1D2 as the follower arm (network)
"""

import yaml
import typer
from pathlib import Path
from typing import Optional, Dict, Any
from rich.prompt import Prompt, Confirm


# Default RealMan R1D2 configuration
DEFAULT_REALMAN_CONFIG = {
    'ip': '192.168.1.18',
    'port': 8080,
    'model': 'R1D2',
    'dof': 6,
    'velocity': 80,
    'collision_level': 3,
    'max_relative_target': 30.0,
    'fixed_joint_4_position': 0.0,
    'gripper_speed': 500,
    'gripper_force': 500,
}

# Model-specific DOF mapping
REALMAN_MODEL_DOF = {
    'R1D2': 6,
    'RM65': 6,
    'RM75': 7,
    'RML63': 6,
    'ECO65': 6,
    'GEN72': 7,
}


def get_realman_config_path() -> Path:
    """Get the path to the RealMan configuration file."""
    # Check multiple locations in priority order
    locations = [
        Path.cwd() / "robot_config.yaml",
        Path.cwd() / "config" / "robot_config.yaml",
        Path.home() / ".solo" / "realman_config.yaml",
        Path(__file__).parent.parent.parent.parent / "config" / "realman_config.yaml",  # solo/config/
    ]
    
    for loc in locations:
        if loc.exists():
            return loc
    
    return None


def load_realman_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load RealMan configuration from YAML file or use defaults.
    
    Args:
        config_path: Path to the YAML configuration file
        
    Returns:
        Dictionary containing RealMan configuration
    """
    config = DEFAULT_REALMAN_CONFIG.copy()
    
    # Try to find config file if not provided
    if config_path is None:
        config_path = get_realman_config_path()
    
    if config_path and config_path.exists():
        try:
            with open(config_path) as f:
                yaml_config = yaml.safe_load(f)
            
            if yaml_config:
                # Extract robot settings
                robot = yaml_config.get('robot', {})
                config['ip'] = robot.get('ip', config['ip'])
                config['port'] = robot.get('port', config['port'])
                config['model'] = robot.get('model', config['model'])
                
                # Set DOF based on model
                model = config['model'].upper()
                config['dof'] = REALMAN_MODEL_DOF.get(model, 6)
                
                # Extract control settings
                control = yaml_config.get('control', {})
                config['velocity'] = control.get('update_rate', config['velocity'])
                
                # Extract safety settings
                safety = yaml_config.get('safety', {})
                config['collision_level'] = safety.get('collision_level', config['collision_level'])
                
                # Extract limits
                limits = yaml_config.get('limits', {})
                config['max_relative_target'] = limits.get('max_joint_velocity', config['max_relative_target'])
                
                # Extract invert joints mapping
                invert_joints = yaml_config.get('invert_joints', {})
                if invert_joints:
                    config['invert_joints'] = invert_joints
                
                # Extract Z safety settings
                min_z = safety.get('min_z_position')
                if min_z is not None:
                    config['min_z_position'] = min_z
                z_limit_action = safety.get('z_limit_action', 'clamp')
                config['z_limit_action'] = z_limit_action
                
            typer.echo(f"📁 Loaded RealMan config from: {config_path}")
        except Exception as e:
            typer.echo(f"⚠️  Could not load config from {config_path}: {e}")
            typer.echo("   Using default configuration")
    
    return config


def prompt_realman_config(existing_config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Interactively prompt user for RealMan configuration.
    
    Args:
        existing_config: Existing configuration to use as defaults
        
    Returns:
        Dictionary containing user-provided configuration
    """
    config = existing_config or DEFAULT_REALMAN_CONFIG.copy()
    
    typer.echo("\n🤖 RealMan Robot Configuration")
    typer.echo("-" * 40)
    
    # IP Address
    config['ip'] = Prompt.ask(
        "RealMan robot IP address",
        default=config['ip']
    )
    
    # Port
    config['port'] = int(Prompt.ask(
        "RealMan robot port",
        default=str(config['port'])
    ))
    
    # Model selection
    typer.echo("\n📋 Select RealMan model:")
    typer.echo("   1. R1D2 (6 DOF)")
    typer.echo("   2. RM65 (6 DOF)")
    typer.echo("   3. RM75 (7 DOF)")
    typer.echo("   4. RML63 (6 DOF)")
    typer.echo("   5. ECO65 (6 DOF)")
    typer.echo("   6. GEN72 (7 DOF)")
    
    model_map = {
        '1': 'R1D2',
        '2': 'RM65',
        '3': 'RM75',
        '4': 'RML63',
        '5': 'ECO65',
        '6': 'GEN72',
    }
    
    # Find default choice number
    default_choice = '1'
    for k, v in model_map.items():
        if v == config['model']:
            default_choice = k
            break
    
    model_choice = Prompt.ask("Select model", default=default_choice)
    config['model'] = model_map.get(model_choice, 'R1D2')
    config['dof'] = REALMAN_MODEL_DOF.get(config['model'], 6)
    
    # Velocity
    config['velocity'] = int(Prompt.ask(
        "Motion velocity (1-100)",
        default=str(config['velocity'])
    ))
    
    # Collision level
    config['collision_level'] = int(Prompt.ask(
        "Collision detection level (0-8, higher=more sensitive)",
        default=str(config['collision_level'])
    ))
    
    typer.echo(f"\n✅ Configuration:")
    typer.echo(f"   • IP: {config['ip']}:{config['port']}")
    typer.echo(f"   • Model: {config['model']} ({config['dof']} DOF)")
    typer.echo(f"   • Velocity: {config['velocity']}")
    typer.echo(f"   • Collision level: {config['collision_level']}")
    
    return config


def save_realman_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> Path:
    """
    Save RealMan configuration to YAML file.
    
    Args:
        config: Configuration dictionary to save
        config_path: Path to save to (defaults to ~/.solo/realman_config.yaml)
        
    Returns:
        Path where configuration was saved
    """
    if config_path is None:
        config_path = Path.home() / ".solo" / "realman_config.yaml"
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    yaml_config = {
        'robot': {
            'ip': config['ip'],
            'port': config['port'],
            'model': config['model'],
        },
        'control': {
            'mode': 'cartesian',
            'update_rate': config.get('velocity', 80),
        },
        'safety': {
            'collision_level': config.get('collision_level', 3),
            'enable_deadman': True,
            'enable_collision_detection': True,
        },
        'limits': {
            'max_joint_velocity': config.get('max_relative_target', 30.0),
        },
    }
    
    with open(config_path, 'w') as f:
        yaml.dump(yaml_config, f, default_flow_style=False)
    
    typer.echo(f"💾 Saved RealMan config to: {config_path}")
    return config_path


def create_realman_follower_config(
    realman_config: Dict[str, Any],
    camera_config: Dict = None,
    follower_id: str = None,
):
    """
    Create RealManFollowerConfig from loaded configuration.
    
    Args:
        realman_config: RealMan configuration dictionary
        camera_config: Camera configuration dictionary
        follower_id: ID for the follower robot
        
    Returns:
        RealManFollowerConfig instance
    """
    from lerobot.robots.realman_follower import RealManFollowerConfig
    from solo.commands.robots.lerobot.config import build_camera_configuration
    
    cameras_dict = build_camera_configuration(camera_config or {})
    
    return RealManFollowerConfig(
        ip=realman_config['ip'],
        port=realman_config['port'],
        model=realman_config['model'],
        dof=realman_config.get('dof', 6),
        velocity=realman_config.get('velocity', 80),
        collision_level=realman_config.get('collision_level', 3),
        max_relative_target=realman_config.get('max_relative_target', 30.0),
        fixed_joint_4_position=realman_config.get('fixed_joint_4_position', 0.0),
        gripper_speed=realman_config.get('gripper_speed', 500),
        gripper_force=realman_config.get('gripper_force', 500),
        invert_joints=realman_config.get('invert_joints', {}),
        min_z_position=realman_config.get('min_z_position'),
        z_limit_action=realman_config.get('z_limit_action', 'clamp'),
        id=follower_id or "realman_r1d2_follower",
        cameras=cameras_dict,
    )


def test_realman_connection(config: Dict[str, Any]) -> bool:
    """
    Test connection to RealMan robot.
    
    Args:
        config: RealMan configuration dictionary
        
    Returns:
        True if connection successful, False otherwise
    """
    typer.echo(f"\n🔌 Testing connection to RealMan at {config['ip']}:{config['port']}...")
    
    try:
        from lerobot.robots.realman_follower.robot_controller import RobotController
        
        # Create controller instance
        controller = RobotController(
            ip=config['ip'],
            port=config['port'],
            model=config['model'],
            dof=config['dof'],
        )
        
        # Try to connect
        if controller.connect():
            typer.echo("✅ Connection successful!")
            
            # Try to get current position
            joints = controller.get_current_joint_angles()
            if joints:
                typer.echo(f"   Current joint angles: {[f'{j:.1f}°' for j in joints]}")
            
            controller.disconnect()
            return True
        else:
            typer.echo("❌ Connection failed - robot may be offline or IP/port incorrect")
            return False
            
    except ImportError as e:
        typer.echo(f"❌ RobotController not found: {e}")
        typer.echo("   Install lerobot with realman extras: pip install -e .[realman]")
        return False
    except Exception as e:
        typer.echo(f"❌ Connection error: {e}")
        return False

