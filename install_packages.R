# r package dependencies

packages <- c(
  "here",
  "tidyverse",
  "plm",
  "lmtest",
  "sandwich",   # robust/clustered SEs (vcovHC) in the acceptance analysis
  "stargazer",
  "ggbreak",
  "xtable",
  "caret",      # confusion matrices in the robustness test + human merge
  "irr"         # Fleiss' kappa (inter-coder reliability) in the same scripts
)

# install packages that are not already installed
install.packages(setdiff(packages, rownames(installed.packages())))

cat("\n✅ All required packages installed!\n")