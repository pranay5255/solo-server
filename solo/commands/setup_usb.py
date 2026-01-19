"""
USB permission setup for Solo CLI
Configures udev rules and user groups for accessing robot USB devices
"""

import os
import subprocess
import sys
from pathlib import Path

import typer


def get_udev_rules_path() -> Path:
    """Get the path to the bundled udev rules file."""
    # The rules file is in solo/udev/99-lerobot.rules
    package_dir = Path(__file__).parent.parent
    return package_dir / "udev" / "99-lerobot.rules"


def check_dialout_membership() -> bool:
    """Check if current user is in the dialout group (Linux only)."""
    try:
        result = subprocess.run(
            ["groups", os.environ.get("USER", "")],
            capture_output=True,
            text=True,
            check=True
        )
        return "dialout" in result.stdout
    except subprocess.CalledProcessError:
        return False


def check_macos_serial_devices() -> list:
    """Check for available serial devices on macOS."""
    serial_devices = []
    dev_path = Path("/dev")
    
    # Look for common USB serial device patterns on macOS
    patterns = ["tty.usbserial*", "tty.usbmodem*", "tty.wchusbserial*", "cu.usbserial*", "cu.usbmodem*"]
    for pattern in patterns:
        serial_devices.extend(dev_path.glob(pattern))
    
    return sorted(set(serial_devices))


def setup_macos():
    """Handle USB setup for macOS."""
    typer.echo("🍎 macOS detected")
    typer.echo("")
    typer.echo("Good news! macOS typically doesn't require special USB permission setup.")
    typer.echo("USB serial devices should be accessible without additional configuration.")
    typer.echo("")
    
    # Check for connected devices
    typer.echo("🔍 Checking for connected USB serial devices...")
    devices = check_macos_serial_devices()
    
    if devices:
        typer.echo(f"   ✅ Found {len(devices)} USB serial device(s):")
        for dev in devices:
            typer.echo(f"      • {dev}")
        typer.echo("")
        typer.echo("🎉 Your USB devices are ready to use!")
    else:
        typer.echo("   ⚠️  No USB serial devices found.")
        typer.echo("")
        typer.echo("💡 Troubleshooting tips:")
        typer.echo("   1. Make sure your robot arm is connected via USB")
        typer.echo("   2. Check that the USB cable supports data transfer (not just charging)")
        typer.echo("   3. Try a different USB port")
        typer.echo("")
        typer.echo("📦 Driver information:")
        typer.echo("   • CH340/CH341 (Waveshare boards): Built-in on macOS 12+")
        typer.echo("     If issues persist, install: https://github.com/WCHSoftGroup/ch34xser_macos")
        typer.echo("   • FTDI (Dynamixel U2D2): Built-in on macOS")
        typer.echo("   • CP210x (Silicon Labs): Built-in on macOS")
    
    typer.echo("")
    typer.echo("After connecting your robot, run 'solo robo --calibrate all' to get started.")


def setup_linux(auto_confirm: bool = False):
    """Handle USB setup for Linux."""
    user = os.environ.get("USER", "")
    
    # Get the udev rules file
    rules_src = get_udev_rules_path()
    rules_dst = Path("/etc/udev/rules.d/99-lerobot.rules")
    
    if not rules_src.exists():
        typer.echo(f"❌ Could not find udev rules file at {rules_src}")
        raise typer.Exit(1)
    
    typer.echo("This will:")
    typer.echo(f"  1. Install udev rules to {rules_dst}")
    typer.echo(f"  2. Add current user to the 'dialout' group")
    typer.echo("  3. Reload udev rules")
    typer.echo("")
    typer.echo("⚠️  Requires sudo privileges.")
    typer.echo("")
    
    # Confirm with user (skip if auto_confirm)
    if not auto_confirm:
        confirm = typer.confirm("Do you want to proceed?", default=True)
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)
    
    typer.echo("")
    
    # Step 1: Copy udev rules
    typer.echo("📋 Step 1: Installing udev rules...")
    try:
        subprocess.run(
            ["sudo", "cp", str(rules_src), str(rules_dst)],
            check=True
        )
        typer.echo(f"   ✅ Installed rules to {rules_dst}")
    except subprocess.CalledProcessError as e:
        typer.echo(f"   ❌ Failed to install udev rules: {e}")
        raise typer.Exit(1)
    
    # Step 2: Add user to dialout group
    if not user:
        typer.echo("   ❌ Could not determine current user")
        raise typer.Exit(1)
    
    typer.echo("👤 Step 2: Adding current user to dialout group...")
    
    if check_dialout_membership():
        typer.echo("   ✅ Already in the dialout group")
    else:
        try:
            subprocess.run(
                ["sudo", "usermod", "-a", "-G", "dialout", user],
                check=True
            )
            typer.echo("   ✅ Added to dialout group")
        except subprocess.CalledProcessError as e:
            typer.echo(f"   ❌ Failed to add user to dialout group: {e}")
            raise typer.Exit(1)
    
    # Step 3: Reload udev rules
    typer.echo("🔄 Step 3: Reloading udev rules...")
    try:
        subprocess.run(
            ["sudo", "udevadm", "control", "--reload-rules"],
            check=True
        )
        subprocess.run(
            ["sudo", "udevadm", "trigger"],
            check=True
        )
        typer.echo("   ✅ Udev rules reloaded")
    except subprocess.CalledProcessError as e:
        typer.echo(f"   ❌ Failed to reload udev rules: {e}")
        raise typer.Exit(1)
    
    typer.echo("")
    typer.echo("✅ USB setup complete!")
    typer.echo("")
    
    # Check if logout is needed
    if not check_dialout_membership():
        typer.echo("⚠️  IMPORTANT: You need to log out and log back in")
        typer.echo("   (or reboot) for the group changes to take effect.")
        typer.echo("")
        typer.echo("   After logging back in, you can verify with:")
        typer.echo("   $ groups")
        typer.echo("   (should include 'dialout')")
    else:
        typer.echo("🎉 You're all set! You can now use 'solo robo' commands")
        typer.echo("   without permission issues.")
    
    typer.echo("")
    typer.echo("💡 If you still have issues, try unplugging and replugging")
    typer.echo("   your USB devices.")


def setup_usb(auto_confirm: bool = False):
    """
    Set up USB permissions for LeRobot-compatible devices.
    
    On Linux:
    - Installs udev rules for USB-to-serial adapters (Dynamixel, Feetech, etc.)
    - Adds current user to the 'dialout' group
    - Reloads udev rules
    
    On macOS:
    - Checks for connected devices and provides driver information if needed
    
    Requires sudo privileges on Linux.
    """
    typer.echo("🔧 Setting up USB permissions for LeRobot devices...")
    typer.echo("")
    
    if sys.platform == "darwin":
        # macOS
        setup_macos()
    elif sys.platform == "linux":
        # Linux
        setup_linux(auto_confirm)
    else:
        typer.echo(f"❌ Unsupported platform: {sys.platform}")
        typer.echo("   This command supports Linux and macOS.")
        raise typer.Exit(1)
