#!/bin/bash

# This script is used to build the agents for the different platforms
# It is intended to be run from the root of the repository.

# build Linux agent
pyinstaller Linux-Agent.spec || echo "Failed to build Linux agent"

# build Windows agent
wine pyinstaller.exe Windows-Agent.spec || echo "Failed to build Windows agent"

# build MacOS agent
darling shell pyinstaller Darwin-Agent.spec || echo "Failed to build MacOS agent"