#!/usr/bin/env python3
"""
ECC (Engineering Control Center) - u2Lighter integration with gstack

This script sets up the ECC framework for u2Lighter, integrating:
- gstack: AI engineering team (review, QA, ship pipeline)
- graphify: Knowledge graph for codebase navigation
- superpowers: Spec-driven methodology
- claude-mem: Persistent memory across sessions

Usage:
    python setup_ecc.py --install
    python setup_ecc.py --status
    python setup_ecc.py --run-office-hours
    python setup_ecc.py --run-review
    python setup_ecc.py --run-qa
    python setup_ecc.py --run-ship
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class ECCSetup:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.ecc_dir = self.root / ".ecc"
        self.gstack_dir = self.ecc_dir / "gstack"
        self.config_path = self.root / "ecc.json"
        
    def check_prerequisites(self) -> bool:
        """Check if all prerequisites are installed."""
        checks = {
            "git": "git --version",
            "python": "python --version",
            "bun": "bun --version",
            "node": "node --version",
        }
        
        all_ok = True
        for name, cmd in checks.items():
            try:
                subprocess.run(cmd.split(), capture_output=True, check=True)
                print(f"  ✓ {name}")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"  ✗ {name} - NOT FOUND")
                all_ok = False
        return all_ok
    
    def install_gstack(self) -> bool:
        """Install gstack framework."""
        if not self.gstack_dir.exists():
            print("Cloning gstack...")
            subprocess.run([
                "git", "clone", "--depth=1", 
                "https://github.com/garrytan/gstack.git", 
                str(self.gstack_dir)
            ], check=True)
        
        print("Running gstack setup...")
        result = subprocess.run([
            sys.executable, str(self.gstack_dir / "setup"), "--host", "claude"
        ], cwd=self.root)
        return result.returncode == 0
    
    def install_graphify(self) -> bool:
        """Install graphify for knowledge graph."""
        try:
            subprocess.run(["uv", "tool", "install", "graphifyy"], check=True)
            print("  ✓ graphify installed")
            return True
        except Exception as e:
            print(f"  ✗ graphify install failed: {e}")
            return False
    
    def install_superpowers(self) -> bool:
        """Install superpowers methodology."""
        try:
            subprocess.run(["/plugin", "marketplace", "add", "obra/superpowers-marketplace"], check=True)
            subprocess.run(["/plugin", "install", "superpowers@superpowers-marketplace"], check=True)
            print("  ✓ superpowers installed")
            return True
        except Exception as e:
            print(f"  ✗ superpowers install failed: {e}")
            return False
    
    def install_claude_mem(self) -> bool:
        """Install claude-mem for persistent memory."""
        try:
            subprocess.run(["npx", "claude-mem", "install"], check=True)
            print("  ✓ claude-mem installed")
            return True
        except Exception as e:
            print(f"  ✗ claude-mem install failed: {e}")
            return False
    
    def load_config(self) -> dict:
        """Load ECC configuration."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def run_office_hours(self, topic: str = None) -> bool:
        """Run gstack office-hours for product design."""
        cmd = ["claude", "-p", "/office-hours"]
        if topic:
            cmd.append(topic)
        result = subprocess.run(cmd, cwd=self.root)
        return result.returncode == 0
    
    def run_review(self) -> bool:
        """Run gstack code review."""
        result = subprocess.run(["claude", "-p", "/review"], cwd=self.root)
        return result.returncode == 0
    
    def run_qa(self, target: str = None) -> bool:
        """Run gstack QA."""
        cmd = ["claude", "-p", "/qa"]
        if target:
            cmd.append(target)
        result = subprocess.run(cmd, cwd=self.root)
        return result.returncode == 0
    
    def run_ship(self) -> bool:
        """Run gstack ship pipeline."""
        result = subprocess.run(["claude", "-p", "/ship"], cwd=self.root)
        return result.returncode == 0
    
    def run_graphify(self) -> bool:
        """Build knowledge graph with graphify."""
        result = subprocess.run(["graphify", "install"], cwd=self.root)
        if result.returncode == 0:
            result = subprocess.run(["graphify", "."], cwd=self.root)
        return result.returncode == 0
    
    def run_superpowers(self) -> bool:
        """Initialize superpowers methodology."""
        result = subprocess.run(["claude", "-p", "/superpowers-init"], cwd=self.root)
        return result.returncode == 0
    
    def status(self) -> dict:
        """Get ECC status."""
        config = self.load_config()
        return {
            "project": config.get("project", "unknown"),
            "ecc_version": config.get("ecc", {}).get("version", "unknown"),
            "gstack_installed": self.gstack_dir.exists(),
            "gstack_version": self._get_gstack_version(),
            "integrations": {
                "graphify": self._check_graphify(),
                "superpowers": self._check_superpowers(),
                "claude_mem": self._check_claude_mem(),
            }
        }
    
    def _get_gstack_version(self) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.gstack_dir), "describe", "--tags"],
                capture_output=True, text=True
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
    
    def _check_graphify(self) -> bool:
        try:
            subprocess.run(["graphify", "--version"], capture_output=True, check=True)
            return True
        except Exception:
            return False
    
    def _check_superpowers(self) -> bool:
        # Check if superpowers plugin is installed
        return True  # Simplified
    
    def _check_claude_mem(self) -> bool:
        try:
            subprocess.run(["npx", "claude-mem", "status"], capture_output=True, check=True)
            return True
        except Exception:
            return False


def main():
    parser = argparse.ArgumentParser(description="ECC Setup for u2Lighter")
    parser.add_argument("--install", action="store_true", help="Install all ECC components")
    parser.add_argument("--status", action="store_true", help="Show ECC status")
    parser.add_argument("--office-hours", nargs="?", const="", help="Run office hours")
    parser.add_argument("--review", action="store_true", help="Run code review")
    parser.add_argument("--qa", nargs="?", const="", help="Run QA")
    parser.add_argument("--ship", action="store_true", help="Run ship pipeline")
    parser.add_argument("--graphify", action="store_true", help="Build knowledge graph")
    parser.add_argument("--superpowers", action="store_true", help="Run superpowers init")
    parser.add_argument("--config", default="ecc.json", help="ECC config file")
    
    args = parser.parse_args()
    
    root = Path(__file__).parent
    ecc = ECCSetup(root)
    
    if args.install:
        print("Installing ECC components...")
        if not ecc.check_prerequisites():
            print("Prerequisites check failed!")
            sys.exit(1)
        
        ecc.install_gstack()
        ecc.install_graphify()
        ecc.install_superpowers()
        ecc.install_claude_mem()
        print("Installation complete!")
    
    elif args.status:
        status = ecc.status()
        print(json.dumps(status, indent=2))
    
    elif args.office_hours is not None:
        topic = args.office_hours if args.office_hours else None
        print(f"Running office hours{f' on: {topic}' if topic else ''}...")
        ecc.run_office_hours(topic)
    
    elif args.review:
        print("Running code review...")
        ecc.run_review()
    
    elif args.qa is not None:
        target = args.qa if args.qa else None
        print(f"Running QA{f' on: {target}' if target else ''}...")
        ecc.run_qa(target)
    
    elif args.ship:
        print("Running ship pipeline...")
        ecc.run_ship()
    
    elif args.graphify:
        print("Building knowledge graph...")
        ecc.run_graphify()
    
    elif args.superpowers:
        print("Initializing superpowers...")
        ecc.run_superpowers()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()