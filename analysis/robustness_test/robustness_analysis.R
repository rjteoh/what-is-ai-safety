# robustness_analysis.R
#
# Measures how well the LLM classifier agrees with human ground-truth labels on the
# held-out test set. Builds confusion matrices and accuracy/precision/recall per
# category, and computes inter-coder reliability (Fleiss' kappa) across the three
# human coders to gauge how hard the labelling task is for humans in the first place.
#
# Key inputs:
#   - input_data/test_data/raw_coder_data/coder_{1,2,3}.csv : the three coders' raw
#     labels (for inter-coder reliability)
#   - input_data/test_data/ground_truth.csv                 : agreed human labels
#     (after group discussion with expert coder) used as the benchmark
#   - output_data/classifiers/test-set-classified.csv       : the classifier's
#     labels on the same test set (produced by abstract_classifier.py --test)
#
# Outputs:
#   To output_data/analysis/robustness_test/ (metrics & diagnostics):
#     - robustness_results.txt  : the printed metrics / confusion matrices
#     - summary_metrics.csv     : per-category accuracy metrics
#     - sample_distribution.csv : label distribution across the test set
#     - misses.csv              : rows where the classifier disagreed with ground truth
#   To paper_figures/ (LaTeX confusion-matrix tables, each with caret metrics):
#     - robustnesscm_main.tex            : main-paper tables for binary safety and
#       overall category assignment
#     - appendix/robustnesscm.tex        : per-category tables, all in one file
#
# Naming note: the variable/column `reliability_safety` is a legacy name kept for
# backwards compatibility across the pipeline. The intended (display) name for this
# category is "Reliability & Robustness" -- that is what is printed in graphs and tables.
#
# Usage: run end-to-end in R/RStudio (uses here() for repo-root-relative paths).

# Load required libraries
library(tidyverse)
library(caret)
library(irr)
library(here)
library(xtable)

rm(list = ls()) # clean env

# load raw human input (for calculating inter-coder reliability)
# Ella
df1 <- read_csv(here("input_data", "test_data",  "raw_coder_data", "coder_1.csv"), show_col_types = FALSE)
# Tyler
df2 <- read_csv(here("input_data", "test_data",  "raw_coder_data", "coder_2.csv"), show_col_types = FALSE)
# RJ
df3 <- read_csv(here("input_data", "test_data",  "raw_coder_data", "coder_3.csv"), show_col_types = FALSE)

# load ground truth df (after group discussion and relabeling)
human <- read_csv(here("input_data", "test_data", "ground_truth.csv"), show_col_types = FALSE)

# load classifier df
llm <- read_csv(here("output_data", "classifiers",  "test-set-classified.csv"), show_col_types = FALSE)

# define column groupings
voting_cols <- c("safety", "indiv_grp_harm", "info_epistemic_harm", "socioec_harm", 
                 "physical_harm", "abstract_harm", "reliability_safety", "bias_inequity", 
                 "security_resilience", "transparency_accountability", "alignment", "governance")
cat_cols <- setdiff(voting_cols, "safety")

# the classifier writes booleans as "True"/"False"; read_csv loads these as
# logical (TRUE/FALSE), not the 0/1 the human labels use. Coerce them to 0/1 so
# they match — otherwise factor(., levels = c(0, 1)) turns every value into NA
# and the confusion matrices come out all zeros.
llm <- llm %>%
  mutate(across(all_of(voting_cols), ~ as.integer(as.logical(.))))

# save misses for analysis
misses <- human %>%
  mutate(
    llm = llm$safety,
    human = human$safety
  ) %>%
  filter(safety != llm)
write_csv(misses, here("output_data", "analysis", "robustness_test", "misses.csv"))

# 1. Confusion Matrix for "safety" column
y_true_safety <- factor(human$safety, levels = c(0, 1))
y_pred_safety <- factor(llm$safety, levels = c(0, 1))
cm_safety <- confusionMatrix(y_pred_safety, y_true_safety, positive = "1")

# 2. Confusion Matrix for category columns

# keep only true positives
true_positives <- which(human$safety == 1 & llm$safety == 1)
human_true <- human %>% slice(true_positives)
llm_true <- llm %>% slice(true_positives)

# create overall CM
# args are (data = prediction, reference = truth), matching cm_safety and the
# per-category CMs below — so rows are the LLM prediction and cols the human label,
# and Sensitivity/Specificity are measured against the human ground truth.
y_true_cat <- factor(unlist(human_true[cat_cols]), levels = c(0, 1))
y_pred_cat <- factor(unlist(llm_true[cat_cols]), levels = c(0, 1))
cm_cat <- confusionMatrix(y_pred_cat, y_true_cat, positive = "1")

# 2b. Individual Confusion Matrices for each category
cm_individual <- list()
for (cat in cat_cols) {
  y_true_ind <- factor(human_true[[cat]], levels = c(0, 1))
  y_pred_ind <- factor(llm_true[[cat]], levels = c(0, 1))
  cm_individual[[cat]] <- confusionMatrix(y_pred_ind, y_true_ind, positive = "1")
}

# 3. Calculate intercoder relaibility

# Calculate percentage agreement
reliability <- df1 %>%
  mutate(
    across(
      .cols = all_of(voting_cols),
      # TRUE if everyone agrees, FALSE otherwise
      .fns = ~ if_else((df1[[cur_column()]] == df2[[cur_column()]] &
                          df2[[cur_column()]] == df3[[cur_column()]]), 1, 0),
      .names = "{.col}"
    )
  )

safety_rel <- mean(reliability$safety) * 100

cat_rel <- reliability %>%
  select(all_of(cat_cols)) %>%
  unlist() %>%
  mean() * 100

# Calculate Fleiss' kappa using vote_sums
fleiss_kappa_results <- list()

for (col in voting_cols) {
  # Create matrix: rows = papers, columns = count of 0s and 1s
  # vote_sums has the sum, so count of 1s = sum, count of 0s = 3 - sum
  ratings_matrix <- cbind(df1[[col]], df2[[col]], df3[[col]])
  
  # Calculate Fleiss' kappa
  fleiss_kappa_results[[col]] <- kappam.fleiss(ratings_matrix)
}

# Extract kappa values
safety_kappa <- fleiss_kappa_results[["safety"]]$value

cat_kappa_values <- sapply(cat_cols, function(col) fleiss_kappa_results[[col]]$value)
cat_kappa_mean <- mean(cat_kappa_values)

# 4. Sample Distribution Statistics
total_papers <- nrow(human)

year_dist <- human %>%
  group_by(year) %>%
  summarise(sample_count = n(), .groups = 'drop') %>%
  mutate(sample_percentage = (sample_count / total_papers) * 100) %>%
  arrange(year)

conf_dist <- human %>%
  group_by(conference) %>%
  summarise(sample_count = n(), .groups = 'drop') %>%
  mutate(sample_percentage = (sample_count / total_papers) * 100) %>%
  arrange(desc(sample_count))

# Read and calculate population distribution
population <- read_csv(here("output_data", "classifiers", "abstracts-classified.csv"), show_col_types=FALSE)

total_population <- nrow(population)

pop_year_dist <- population %>%
  group_by(year) %>%
  summarise(population_count = n(), .groups = 'drop') %>%
  mutate(population_percentage = (population_count / total_population) * 100) %>%
  arrange(year)

pop_conf_dist <- population %>%
  group_by(conference) %>%
  summarise(population_count = n(), .groups = 'drop') %>%
  mutate(population_percentage = (population_count / total_population) * 100) %>%
  arrange(desc(population_count))

# Merge sample and population distributions
year_combined <- year_dist %>%
  full_join(pop_year_dist, by = "year") %>%
  replace_na(list(sample_count = 0, sample_percentage = 0, 
                  population_count = 0, population_percentage = 0))
conf_combined <- conf_dist %>%
  full_join(pop_conf_dist, by = "conference") %>%
  replace_na(list(sample_count = 0, sample_percentage = 0, 
                  population_count = 0, population_percentage = 0))

# Combine distributions into single dataframe
sample_distribution <- bind_rows(
  year_combined %>% mutate(type = "year") %>% rename(category = year) %>% mutate(category = as.character(category)),
  conf_combined %>% mutate(type = "conference") %>% rename(category = conference)
) %>%
  select(type, category, sample_count, sample_percentage,
         population_count, population_percentage)

# 5. Print and Save Stats

# save terminal output to file
sink(here("output_data", "analysis", "robustness_test", "robustness_results.txt"))
cat("\n=== Confusion Matrix: LLM vs Human for Safety ===\n")
print(cm_safety)
cat("\n=== Confusion Matrix: LLM vs Human for Categorization (Overall) ===\n")
print(cm_cat)
cat("\n=== Individual Confusion Matrices by Category ===\n")
for (cat in cat_cols) {
  cat(sprintf("\n--- %s ---\n", cat))
  print(cm_individual[[cat]])
}
cat("\n=== Intercoder Reliability ===\n")
cat("\n--- Percentage Agreement ---\n")
cat(sprintf("Safety: %.2f%%\n", safety_rel))
cat(sprintf("Categorization (average): %.2f%%\n", cat_rel))
for (col in cat_cols) {
  cat(sprintf("%s: %.2f%%\n", col, mean(reliability[[col]]) * 100))
}
cat("\n--- Fleiss' Kappa ---\n")
cat(sprintf("Safety: %.4f\n", safety_kappa))
cat(sprintf("Categorization (average): %.4f\n", cat_kappa_mean))
cat("\nIndividual Category Kappa Values:\n")
for (col in cat_cols) {
  cat(sprintf("  %s: %.4f\n", col, fleiss_kappa_results[[col]]$value))
}
  replace_na(list(sample_count = 0, sample_percentage = 0, 
                  population_count = 0, population_percentage = 0))
sink() # close sink

# create and save summary metrics
summary_metrics <- tibble(
  category = c("Safety", "Categorization (Overall)", cat_cols),
  accuracy = c(
    cm_safety$overall["Accuracy"], 
    cm_cat$overall["Accuracy"],
    sapply(cat_cols, function(cat) cm_individual[[cat]]$overall["Accuracy"])
  )
)
write_csv(summary_metrics, here("output_data", "analysis", "robustness_test", "summary_metrics.csv"))

# save distribution statistics
write_csv(sample_distribution, here("output_data", "analysis", "robustness_test", "sample_distribution.csv"))

# readable labels for the category columns (mirrors analysis_safety.R)
category_labels <- c(
  indiv_grp_harm              = "Individual/Group Harm",
  info_epistemic_harm         = "Info & Epistemic Harm",
  socioec_harm                = "Socioeconomic Harm",
  physical_harm               = "Physical Harm",
  abstract_harm               = "Abstract Harm",
  reliability_safety          = "Reliability & Robustness",
  bias_inequity               = "Bias & Inequity",
  security_resilience         = "Security & Resilience",
  transparency_accountability = "Transparency & Accountability",
  alignment                   = "Alignment",
  governance                  = "Governance"
)

# save the confusion matrices as LaTeX tables for the paper. Each table shows the
# 2x2 confusion matrix (classifier output x human label) followed by the key caret
# metrics (accuracy, kappa, sensitivity, etc.). The metric rows use \multicolumn,
# which xtable can't produce from a plain data frame, so we build the LaTeX by hand.

# format a metric to 3 decimal places
fmt <- function(x) formatC(x, format = "f", digits = 3)

# build a standalone LaTeX table block for one caret confusionMatrix (caption +
# 2x2 table + metric rows). Used for the main-paper tables, one table each. Assumes
# cm$table has rows = classifier prediction and cols = human reference (levels 0, 1).
# `neg_lab` / `pos_lab` label the two classes (and double as the column headers).
cm_latex_table <- function(cm, title, label, neg_lab, pos_lab) {
  tab <- cm$table
  metrics <- c(
    "Accuracy"             = cm$overall[["Accuracy"]],
    "Kappa ($\\kappa$)"    = cm$overall[["Kappa"]],
    "Sensitivity (Recall)" = cm$byClass[["Sensitivity"]],
    "Specificity"          = cm$byClass[["Specificity"]],
    "Balanced Accuracy"    = cm$byClass[["Balanced Accuracy"]]
  )
  c(
    "\\begin{table}[ht]",
    "\\centering",
    sprintf("\\caption{%s}", title),
    sprintf("\\label{%s}", label),
    "\\begin{tabular}{lcc}",
    "\\hline",
    sprintf("\\textbf{Classifier Output} & \\textbf{%s} & \\textbf{%s} \\\\", neg_lab, pos_lab),
    "\\hline",
    sprintf("%s & %d & %d \\\\", neg_lab, as.integer(tab[1, 1]), as.integer(tab[1, 2])),
    sprintf("%s & %d & %d \\\\", pos_lab, as.integer(tab[2, 1]), as.integer(tab[2, 2])),
    "\\hline",
    sprintf("%s & \\multicolumn{2}{c}{%s} \\\\", names(metrics), fmt(metrics)),
    "\\hline",
    "\\end{tabular}",
    "\\end{table}",
    ""
  )
}

# build the inner minipage block for one caret confusionMatrix (caption + 2x2
# table + metric rows). Two of these are placed side by side inside a single table
# environment, so the appendix matrices come out two-by-two. Same assumptions as
# cm_latex_table() above.
cm_minipage <- function(cm, title, label, neg_lab, pos_lab) {
  tab <- cm$table
  metrics <- c(
    "Accuracy"             = cm$overall[["Accuracy"]],
    "Kappa ($\\kappa$)"    = cm$overall[["Kappa"]],
    "Sensitivity (Recall)" = cm$byClass[["Sensitivity"]],
    "Specificity"          = cm$byClass[["Specificity"]],
    "Balanced Accuracy"    = cm$byClass[["Balanced Accuracy"]]
  )
  c(
    "\\begin{minipage}{0.48\\textwidth}",
    "\\centering",
    sprintf("\\caption{%s}", title),
    sprintf("\\label{%s}", label),
    "\\begin{tabular}{lcc}",
    "\\hline",
    sprintf("\\textbf{Classifier Output} & \\textbf{%s} & \\textbf{%s} \\\\", neg_lab, pos_lab),
    "\\hline",
    sprintf("%s & %d & %d \\\\", neg_lab, as.integer(tab[1, 1]), as.integer(tab[1, 2])),
    sprintf("%s & %d & %d \\\\", pos_lab, as.integer(tab[2, 1]), as.integer(tab[2, 2])),
    "\\hline",
    sprintf("%s & \\multicolumn{2}{c}{%s} \\\\", names(metrics), fmt(metrics)),
    "\\hline",
    "\\end{tabular}",
    "\\end{minipage}"
  )
}

# write a list of confusion-matrix specs to `out`, two side-by-side minipages per
# table environment. A lone trailing matrix (odd count) gets its own table. Each
# spec is a named list matching cm_minipage()'s arguments.
write_cm_tables <- function(specs, out) {
  if (file.exists(out)) file.remove(out)
  for (i in seq(1, length(specs), by = 2)) {
    block <- c("\\begin{table}[h!]", do.call(cm_minipage, specs[[i]]))
    if (i + 1 <= length(specs)) {
      block <- c(block, "\\hfill", "\\hfill", do.call(cm_minipage, specs[[i + 1]]))
    }
    block <- c(block, "\\end{table}", "")
    cat(block, file = out, sep = "\n", append = TRUE)
  }
}

# (1) main-paper tables: binary safety + overall category assignment. Saved
# directly in paper_figures/ (not the appendix) as these are main-paper tables.
# These stay one-table-each (not the two-by-two appendix layout).
main_latex_out <- here("paper_figures", "robustnesscm_main.tex")
if (file.exists(main_latex_out)) file.remove(main_latex_out)
cat(
  c(
    cm_latex_table(
      cm_safety,
      title   = "Classifier Performance on Binary Safety Classification",
      label   = "tab:cm-safety",
      neg_lab = "Not Safety (0)",
      pos_lab = "Safety (1)"
    ),
    cm_latex_table(
      cm_cat,
      title   = "Classifier Performance on Category Assignment (Overall)",
      label   = "tab:cm-overall",
      neg_lab = "Not Assigned (0)",
      pos_lab = "Assigned (1)"
    )
  ),
  file = main_latex_out, sep = "\n", append = TRUE
)

# (2) per-category tables for the appendix, all appended into a single file, two
# side by side per table. (No HTML copy: the matrices are already sunk into the
# .txt output above for browsing.)
cat_specs <- lapply(cat_cols, function(col) {
  cat_label <- gsub("&", "\\\\&", category_labels[[col]])  # escape & for LaTeX
  list(cm = cm_individual[[col]],
       title   = sprintf("Classifier Performance on Category Assignment (%s)", cat_label),
       label   = sprintf("tab:cm-%s", gsub("_", "-", col)),
       neg_lab = "Not Assigned (0)",
       pos_lab = "Assigned (1)")
})
write_cm_tables(cat_specs, here("paper_figures", "appendix", "robustnesscm.tex"))