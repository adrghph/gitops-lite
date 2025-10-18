"""
Local rendering engine for Kustomize and Helm charts.

This module provides optional manifest rendering before apply/diff operations.
All rendering happens locally - nothing is installed in the cluster.
"""

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rich.console import Console

console = Console()


class RendererType(str, Enum):
    """Supported renderer types."""

    NONE = "none"
    KUSTOMIZE = "kustomize"


@dataclass
class RendererConfig:
    """Configuration for manifest rendering."""

    renderer_type: RendererType
    # Kustomize options
    kustomize_dir: str | None = None  # Path to kustomization.yaml dir
    kustomize_build_args: list[str] | None = None  # Additional args for kustomize build (e.g., --enable-helm)


def check_renderer_available(renderer_type: RendererType) -> tuple[bool, str]:
    """
    Check if the required renderer binary is available.

    Args:
        renderer_type: Type of renderer to check

    Returns:
        Tuple of (is_available, version_or_error)
    """
    if renderer_type == RendererType.NONE:
        return True, "N/A"

    if renderer_type == RendererType.KUSTOMIZE:
        try:
            result = subprocess.run(
                ["kustomize", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Extract version from output
                version = result.stdout.strip().split("\n")[0]
                return True, version
            return False, f"kustomize command failed: {result.stderr}"
        except FileNotFoundError:
            return False, "kustomize binary not found in PATH"
        except subprocess.TimeoutExpired:
            return False, "kustomize version check timed out"

    return False, f"Unknown renderer type: {renderer_type}"


def render_kustomize(kustomize_dir: str, build_args: list[str] | None = None) -> str:
    """
    Render Kustomize manifests using 'kustomize build'.

    Args:
        kustomize_dir: Path to directory containing kustomization.yaml
        build_args: Additional arguments to pass to kustomize build (e.g., ['--enable-helm'])

    Returns:
        Rendered YAML as string

    Raises:
        RuntimeError: If kustomize command fails
    """
    kustomize_path = Path(kustomize_dir).resolve()
    if not kustomize_path.exists():
        raise RuntimeError(f"Kustomize directory does not exist: {kustomize_dir}")

    kustomization_file = kustomize_path / "kustomization.yaml"
    if not kustomization_file.exists():
        raise RuntimeError(
            f"kustomization.yaml not found in {kustomize_dir}\n"
            f"Expected: {kustomization_file}"
        )

    console.print(f"[dim]Rendering Kustomize from {kustomize_dir}...[/dim]")

    # Build command
    cmd = ["kustomize", "build", str(kustomize_path)]
    if build_args:
        cmd.extend(build_args)
        console.print(f"[dim]  Extra args: {' '.join(build_args)}[/dim]")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        if not result.stdout.strip():
            raise RuntimeError("Kustomize build produced empty output")

        console.print("[green][OK][/green] Kustomize rendering complete")
        return result.stdout

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Kustomize build failed:\n{e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Kustomize build timed out (60s)")




def render_manifests(config: RendererConfig, namespace: str = "default") -> str:
    """
    Render manifests based on configuration.

    This is the main entry point for rendering. Currently only supports Kustomize.
    For Helm charts, use Kustomize's helmCharts feature with --enable-helm flag.

    Args:
        config: Renderer configuration
        namespace: Target namespace (informational only, not used with Kustomize)

    Returns:
        Rendered YAML string (or raises RuntimeError)

    Raises:
        RuntimeError: If rendering fails or config is invalid
    """
    if config.renderer_type == RendererType.NONE:
        raise ValueError("Cannot render with renderer_type=NONE")

    # Check renderer availability
    available, version_or_error = check_renderer_available(config.renderer_type)
    if not available:
        raise RuntimeError(
            f"Renderer '{config.renderer_type}' is not available:\n{version_or_error}\n\n"
            f"Please install it before using this renderer type."
        )

    console.print(f"[dim]Using {config.renderer_type} ({version_or_error})[/dim]")

    if config.renderer_type == RendererType.KUSTOMIZE:
        if not config.kustomize_dir:
            raise ValueError("kustomize_dir is required for Kustomize rendering")
        return render_kustomize(
            kustomize_dir=config.kustomize_dir,
            build_args=config.kustomize_build_args or [],
        )

    raise ValueError(f"Unknown renderer type: {config.renderer_type}")
