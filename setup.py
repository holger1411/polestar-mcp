from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="polestar-mcp-server",
    version="0.1.0",
    description="MCP Server for Polestar 2 vehicle data (unofficial, reverse-engineered API)",
    author="Holger Koenemann",
    url="https://github.com/holger1411/polestar-mcp",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "polestar-mcp-server=polestar_mcp_server.server:main"
        ]
    },
)
