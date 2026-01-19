"""
Motor scanning utilities for LeRobot
Scans all serial ports for connected Dynamixel and Feetech motors
"""

import sys
from pathlib import Path
from typing import Optional
import typer


# Motor model number to name mapping
DYNAMIXEL_MODELS = {
    1060: "XL430-W250",
    1190: "XL330-M077",
    1200: "XL330-M288",
    1020: "XM430-W350",
    1120: "XM540-W270",
    1070: "XC430-W150",
}

FEETECH_MODELS = {
    777: "STS3215",
    2825: "STS3250",
}

# Motor models typically used in leader vs follower arms
# Leader arms use lighter motors (XL330-M077) for ease of manual control
# Follower arms use stronger motors (XL430, XL330-M288) for payload
KOCH_LEADER_MODELS = {1190}  # XL330-M077 only
KOCH_FOLLOWER_MODELS = {1060, 1200, 1020, 1120, 1070}  # XL430, XL330-M288, etc.


def get_serial_ports() -> list[str]:
    """Get available serial ports for motor scanning."""
    ports = []
    
    # Linux/macOS
    if sys.platform != "win32":
        dev = Path("/dev")
        # Common robot arm serial ports
        patterns = ["ttyACM*", "ttyUSB*"]
        for pattern in patterns:
            ports.extend(str(p) for p in dev.glob(pattern))
    else:
        # Windows - use pyserial to find COM ports
        try:
            from serial.tools import list_ports
            ports = [port.device for port in list_ports.comports()]
        except ImportError:
            typer.echo("⚠️  pyserial required for Windows port detection")
    
    return sorted(ports)


def scan_dynamixel_port(port: str, baudrate: int = 1_000_000) -> dict[int, int]:
    """Scan a port for Dynamixel motors. Returns {motor_id: model_number}."""
    try:
        import dynamixel_sdk as dxl
    except ImportError:
        return {}
    
    found = {}
    try:
        port_handler = dxl.PortHandler(port)
        packet_handler = dxl.PacketHandler(2.0)  # Protocol 2.0
        
        if not port_handler.openPort():
            return {}
        
        port_handler.setBaudRate(baudrate)
        
        # Scan motor IDs 1-20
        for motor_id in range(1, 21):
            model_number, result, _ = packet_handler.ping(port_handler, motor_id)
            if result == dxl.COMM_SUCCESS:
                found[motor_id] = model_number
        
        port_handler.closePort()
    except Exception:
        pass
    
    return found


def scan_feetech_port(port: str, baudrate: int = 1_000_000) -> dict[int, int]:
    """Scan a port for Feetech motors. Returns {motor_id: model_number}."""
    try:
        from lerobot.motors.feetech import FeetechMotorsBus
    except ImportError:
        return {}
    
    # Feetech scanning is more complex - skip for now
    # The broadcast_ping method requires motor definitions
    return {}


def detect_arm_type_from_models(models: set[int]) -> Optional[str]:
    """Detect whether motors indicate a leader or follower arm."""
    if not models:
        return None
    
    # Koch arms detection
    if models.issubset(KOCH_LEADER_MODELS):
        return "leader"
    elif models & KOCH_FOLLOWER_MODELS:  # Has any follower-type motors
        return "follower"
    
    return None


def auto_detect_ports(robot_type: str = "koch", verbose: bool = True) -> tuple[Optional[str], Optional[str]]:
    """
    Auto-detect leader and follower ports based on connected motor types.
    
    Returns (leader_port, follower_port) or (None, None) if detection failed.
    """
    if verbose:
        typer.echo("🔍 Auto-detecting arm ports...")
    
    ports = get_serial_ports()
    
    if not ports:
        if verbose:
            typer.echo("❌ No serial ports found")
        return None, None
    
    leader_port = None
    follower_port = None
    port_info = []
    
    for port in ports:
        motors = scan_dynamixel_port(port)
        if motors:
            models = set(motors.values())
            arm_type = detect_arm_type_from_models(models)
            port_info.append((port, motors, arm_type))
            
            if arm_type == "leader" and leader_port is None:
                leader_port = port
            elif arm_type == "follower" and follower_port is None:
                follower_port = port
    
    if verbose:
        if leader_port or follower_port:
            typer.echo("✅ Auto-detected ports:")
            if leader_port:
                typer.echo(f"   • Leader:   {leader_port}")
            if follower_port:
                typer.echo(f"   • Follower: {follower_port}")
        else:
            typer.echo("⚠️  Could not auto-detect arm types")
            if port_info:
                typer.echo("   Found motors but couldn't determine leader/follower:")
                for port, motors, _ in port_info:
                    typer.echo(f"   • {port}: {len(motors)} motors")
    
    return leader_port, follower_port


def auto_detect_single_port(arm_type: str, robot_type: str = "koch", verbose: bool = True) -> Optional[str]:
    """
    Auto-detect a single arm port (leader or follower).
    
    Args:
        arm_type: "leader" or "follower"
        robot_type: Robot type (e.g., "koch")
        verbose: Whether to print status messages
    
    Returns the detected port or None.
    """
    leader_port, follower_port = auto_detect_ports(robot_type, verbose=False)
    
    if arm_type == "leader":
        port = leader_port
    elif arm_type == "follower":
        port = follower_port
    else:
        return None
    
    if verbose:
        if port:
            typer.echo(f"✅ Auto-detected {arm_type} arm on {port}")
        else:
            typer.echo(f"⚠️  Could not auto-detect {arm_type} arm")
    
    return port


def scan_motors():
    """Scan all serial ports for connected motors and display results."""
    typer.echo("🔍 Scanning for connected motors...\n")
    
    ports = get_serial_ports()
    
    if not ports:
        typer.echo("❌ No serial ports found.")
        typer.echo("\n💡 Tips:")
        typer.echo("   • Make sure your robot arm is connected via USB")
        typer.echo("   • Run 'solo setup-usb' to configure USB permissions")
        return
    
    typer.echo(f"📡 Found {len(ports)} serial port(s):\n")
    
    found_any = False
    
    for port in ports:
        typer.echo(f"━━━ {port} ━━━")
        
        # Try Dynamixel first (Koch arms)
        dynamixel_motors = scan_dynamixel_port(port)
        
        if dynamixel_motors:
            found_any = True
            typer.echo("  Dynamixel motors (Protocol 2.0):")
            for motor_id, model_num in sorted(dynamixel_motors.items()):
                model_name = DYNAMIXEL_MODELS.get(model_num, f"Unknown ({model_num})")
                typer.echo(f"    ✅ ID {motor_id}: {model_name}")
            
            # Detect arm type based on motor models
            models = set(dynamixel_motors.values())
            if models == {1190}:  # All XL330-M077
                typer.echo("    → Likely: Koch Leader arm")
            elif 1060 in models or 1200 in models:  # XL430 or XL330-M288
                typer.echo("    → Likely: Koch Follower arm")
        else:
            # Could be Feetech (SO100/SO101)
            typer.echo("  (No Dynamixel motors found - may be Feetech/SO100/SO101)")
        
        typer.echo("")
    
    if not found_any:
        typer.echo("⚠️  No motors responded on any port.\n")
        typer.echo("💡 Troubleshooting:")
        typer.echo("   1. Make sure the arm is POWERED (12V for Dynamixel)")
        typer.echo("   2. Check that motor cables are firmly connected")
        typer.echo("   3. Run 'solo setup-usb' if you have permission issues")
        typer.echo("   4. Try unplugging and replugging the USB cable")
    else:
        typer.echo("✅ Motor scan complete!")
        typer.echo("\n💡 To start teleoperation:")
        typer.echo("   solo robo --teleop")


def diagnose_connection(port: str, verbose: bool = True) -> dict:
    """
    Run detailed diagnostics on a motor connection.
    Returns dict with diagnostic results.
    """
    results = {
        "port": port,
        "ping_success": False,
        "motors_found": {},
        "arm_type": None,  # "leader" or "follower"
        "min_position_limit_read": False,
        "present_position_read": False,
        "errors": []
    }
    
    try:
        import dynamixel_sdk as dxl
    except ImportError:
        results["errors"].append("dynamixel_sdk not installed")
        return results
    
    if verbose:
        typer.echo(f"\n🔍 Diagnosing connection on {port}...")
    
    try:
        port_handler = dxl.PortHandler(port)
        packet_handler = dxl.PacketHandler(2.0)
        
        # Step 1: Open port
        if verbose:
            typer.echo("  1️⃣  Opening port...", nl=False)
        if not port_handler.openPort():
            results["errors"].append("Failed to open port")
            if verbose:
                typer.echo(" ❌")
            return results
        if verbose:
            typer.echo(" ✅")
        
        # Step 2: Set baud rate
        if verbose:
            typer.echo("  2️⃣  Setting baud rate (1M)...", nl=False)
        port_handler.setBaudRate(1_000_000)
        if verbose:
            typer.echo(" ✅")
        
        # Step 3: Ping motors
        if verbose:
            typer.echo("  3️⃣  Pinging motors...")
        for motor_id in range(1, 7):
            model_number, result, error = packet_handler.ping(port_handler, motor_id)
            if result == dxl.COMM_SUCCESS:
                model_name = DYNAMIXEL_MODELS.get(model_number, f"Unknown({model_number})")
                results["motors_found"][motor_id] = model_number
                if verbose:
                    typer.echo(f"       ID {motor_id}: {model_name} ✅")
            else:
                if verbose:
                    typer.echo(f"       ID {motor_id}: No response ❌")
        
        results["ping_success"] = len(results["motors_found"]) > 0
        
        if not results["ping_success"]:
            results["errors"].append("No motors responded to ping")
            port_handler.closePort()
            return results
        
        # Detect arm type based on motor models
        models = set(results["motors_found"].values())
        results["arm_type"] = detect_arm_type_from_models(models)
        
        if verbose and results["arm_type"]:
            arm_label = "🎮 LEADER" if results["arm_type"] == "leader" else "🤖 FOLLOWER"
            typer.echo(f"       → Detected: {arm_label} arm")
        
        # Step 4: Try reading Min_Position_Limit (the failing operation)
        if verbose:
            typer.echo("  4️⃣  Reading Min_Position_Limit...")
        
        # Address for Min_Position_Limit on X-series
        MIN_POS_ADDR = 52
        MIN_POS_LEN = 4
        
        for motor_id in results["motors_found"].keys():
            value, result, error = packet_handler.read4ByteTxRx(
                port_handler, motor_id, MIN_POS_ADDR
            )
            if result == dxl.COMM_SUCCESS:
                if verbose:
                    typer.echo(f"       ID {motor_id}: {value} ✅")
                results["min_position_limit_read"] = True
            else:
                error_msg = packet_handler.getTxRxResult(result)
                if verbose:
                    typer.echo(f"       ID {motor_id}: {error_msg} ❌")
                results["errors"].append(f"ID {motor_id} Min_Position_Limit read failed: {error_msg}")
        
        # Step 5: Try reading Present_Position
        if verbose:
            typer.echo("  5️⃣  Reading Present_Position...")
        
        PRESENT_POS_ADDR = 132
        PRESENT_POS_LEN = 4
        
        for motor_id in results["motors_found"].keys():
            value, result, error = packet_handler.read4ByteTxRx(
                port_handler, motor_id, PRESENT_POS_ADDR
            )
            if result == dxl.COMM_SUCCESS:
                if verbose:
                    typer.echo(f"       ID {motor_id}: {value} ✅")
                results["present_position_read"] = True
            else:
                error_msg = packet_handler.getTxRxResult(result)
                if verbose:
                    typer.echo(f"       ID {motor_id}: {error_msg} ❌")
                results["errors"].append(f"ID {motor_id} Present_Position read failed: {error_msg}")
        
        port_handler.closePort()
        
    except Exception as e:
        results["errors"].append(str(e))
        if verbose:
            typer.echo(f"  ❌ Error: {e}")
    
    if verbose:
        typer.echo("")
        if results["errors"]:
            typer.echo("⚠️  Issues found:")
            for err in results["errors"]:
                typer.echo(f"   • {err}")
        else:
            typer.echo("✅ All diagnostics passed!")
    
    return results


def diagnose_all_ports():
    """Run diagnostics on all detected serial ports."""
    typer.echo("🔬 Running connection diagnostics...\n")
    
    ports = get_serial_ports()
    
    if not ports:
        typer.echo("❌ No serial ports found")
        return
    
    for port in ports:
        diagnose_connection(port, verbose=True)
        typer.echo("")


if __name__ == "__main__":
    scan_motors()

