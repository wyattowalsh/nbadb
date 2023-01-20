#!/bin/bash

# Update homebrew recipes
echo "Updating homebrew..."
brew update

echo "Installing Git..."
brew install git
brew install gh

# Apps
apps=(
  miniconda
)

# Install apps to /Applications
# Default is: /Users/$user/Applications
echo "installing apps with Cask..."
brew install --cask --appdir="/Applications" "${apps[@]}"

conda init "$(basename "${SHELL}")"
conda config --add channels conda-forge
conda config --set auto_activate_base false

conda env create -f environment.yml

conda activate nba_db

nbdime config-git --enable --global
nbdime extensions --enable

brew cleanup