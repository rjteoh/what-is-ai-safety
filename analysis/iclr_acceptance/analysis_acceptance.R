# analysis_acceptance.R
#
# Compares ICLR safety vs non-safety papers on acceptance. It combines the
# classified accepted papers (abstracts-classified.csv, iclr only) with the
# classified rejected papers (iclr-rejects-classified.csv), then:
#   - tabulates per-year acceptance rates for safety vs non-safety and per
#     category, saving stats + plots
#   - fits linear probability models of acceptance on the safety flag
#   - estimates per-year safety coefficients with a measurement-error band
#   - re-fits the acceptance LPM on papers_withdrawn (accepted + rejected +
#     withdrawn, with withdrawn counted as not accepted) for a separate table
#
# Outputs:
#   - HTML tables / CSVs / plots -> output_data/analysis/iclr_acceptance/. The
#     withdrawn variant of the acceptance regression is suffixed _withdrawn.
#   - LaTeX copies of paper tables -> paper_figures/ (main paper) and
#     paper_figures/appendix/ (the withdrawn variant), via robust_stargazer().
#
# Naming note: the column `reliability_safety` (used in cat_cols) is a legacy name
# kept for backwards compatibility across the pipeline. The intended (display) name
# for this category is "Reliability & Robustness". This script only references the
# column as data and does not render the label, but the note is kept for consistency.
#
# COMMENT:
# The per-year measurement-error band comes from a simulation that perturbs the
# classifier safety labels to reflect its imperfect accuracy: every label is
# flipped independently at a single error rate (safety_error_rate) from the
# June 22 robustness run. See bootstrap_coef() below. Because random label
# flipping attenuates the coefficient toward zero, the simulated results are
# systematically shifted toward zero. This causes to point-estimate to
# falls outside their 95% spread whenever a year's effect is large enough. 
# The simulation is therefore primarily used to size the uncertainty (its spread) 
# and is re-anchored on the observed point instead of reporting the raw results.
# This methodology doesn't reflect that our classifier tends to label conservatively —
# a future version might flip safety and non-safety papers at different rates.

library(here)
library(tidyverse)
library(lmtest)
library(sandwich)
library(stargazer)

# clean env
rm(list = ls())

# Classifier misclassification rate from the June 22 robustness run.
# Set to NA to suppress the uncertainty band.
safety_error_rate <- 0.155

# mirrors robust_stargazer from analysis_safety.R. `output` is a bare filename.
# Always writes the HTML table to this analysis's output folder. If the table
# goes in the main paper, also writes a LaTeX copy into the project-root
# paper_figures/ folder (one home for every paper figure). stargazer picks the
# format per file from its extension, so both come from a single call.
robust_stargazer <- function(..., output, dep_var = NULL, co_var = NULL,
                             column.labels = NULL, column.separate = NULL,
                             dep_var_include = TRUE, in_main_paper = FALSE,
                             in_appendix = FALSE,
                             omit = NULL, add.lines = NULL, notes = NULL) {
  models <- list(...)
  # calculate robust SEs
  se_list <- lapply(models, function(model) {
    if (inherits(model, "plm")) {
      sqrt(diag(vcovHC(model, type = "HC1", cluster = "group")))  # clustering for panel lm
    } else {
      sqrt(diag(vcovHC(model, type = "HC1")))  # no clustering for lm
    }
  })

  # Always write the HTML table to this analysis's output folder. Optionally also
  # write a LaTeX copy: main-paper tables go to paper_figures/, appendix tables to
  # paper_figures/appendix/. stargazer picks the format per file from its extension.
  out_paths <- here("output_data", "analysis", "iclr_acceptance", output)
  tex_name <- paste0(tools::file_path_sans_ext(output), ".tex")
  if (in_main_paper) {
    paper_dir <- here("paper_figures")
    if (!dir.exists(paper_dir)) dir.create(paper_dir, recursive = TRUE)
    out_paths <- c(out_paths, file.path(paper_dir, tex_name))
  }
  if (in_appendix) {
    appendix_dir <- here("paper_figures", "appendix")
    if (!dir.exists(appendix_dir)) dir.create(appendix_dir, recursive = TRUE)
    out_paths <- c(out_paths, file.path(appendix_dir, tex_name))
  }

  stargazer(...,
            type = "html",
            se = se_list,
            dep.var.labels = dep_var,
            dep.var.labels.include = dep_var_include,
            covariate.labels = co_var,
            column.labels = column.labels,
            column.separate = column.separate,
            omit = omit,
            add.lines = add.lines,
            notes = notes,
            out = out_paths)
}

# define category columns
cat_cols <- c("indiv_grp_harm", "info_epistemic_harm", "socioec_harm",
                 "physical_harm", "abstract_harm", "reliability_safety",
                 "bias_inequity", "security_resilience",
                 "transparency_accountability", "alignment", "governance")

# load and combine data with accepted boolean column.
papers <- bind_rows(
  read_csv(here("output_data/classifiers/iclr-rejects-classified.csv")) %>%
    mutate(uid = as.character(uid), accepted = FALSE, withdrawn = FALSE),
  read_csv(here("output_data/classifiers/abstracts-classified.csv")) %>%
    filter(conference == "iclr", year >= 2017) %>%
    mutate(uid = as.character(uid), accepted = TRUE, withdrawn = FALSE)
)

# summarize by year and acceptance status, then pivot to wide _acc/_rej columns
summarize_by_year <- function(df) {
  df %>%
    mutate(accepted = if_else(accepted, "acc", "rej")) %>%
    group_by(year, accepted) %>%
    summarize(
      paper_n  = n(),
      safety_n = sum(safety, na.rm = TRUE),
      across(all_of(cat_cols),
             list(n = \(x) sum(x, na.rm = TRUE)),
             .names = "{.col}_{.fn}"),
      .groups = "drop"
    ) %>%
    pivot_wider(
      names_from  = accepted,
      values_from = -c(year, accepted),
      names_glue  = "{.value}_{accepted}"
    )
}

df_wide <- summarize_by_year(papers)

# build comparison df
df <- df_wide %>%
  mutate(
    safety_total    = safety_n_acc + safety_n_rej,
    safety_acc_pct  = safety_n_acc / safety_total * 100,

    nonsafety_acc     = paper_n_acc - safety_n_acc,
    nonsafety_rej     = paper_n_rej - safety_n_rej,
    nonsafety_total   = nonsafety_acc + nonsafety_rej,
    nonsafety_acc_pct = nonsafety_acc / nonsafety_total * 100
  ) %>%
  select(year, safety_n_acc, safety_n_rej, safety_total, safety_acc_pct,
         nonsafety_acc, nonsafety_rej, nonsafety_total, nonsafety_acc_pct,
         ends_with("_n_acc"), ends_with("_n_rej"))

# add per-category acceptance rates
df <- df %>%
  bind_cols(map_dfc(cat_cols, \(col) {
    acc <- df[[paste0(col, "_n_acc")]]
    rej <- df[[paste0(col, "_n_rej")]]
    tibble(!!paste0(col, "_acc_pct") := acc / (acc + rej) * 100)
  }))


write_excel_csv(df %>% select(year, sort(colnames(df)[-1])),
                file = here("output_data/analysis/iclr_acceptance/acceptance-stats.csv"))

# theme
windowsFonts(Times = windowsFont("Times New Roman"))
theme_set(theme_minimal(base_size = 34, base_family = "Times") +
  theme(legend.position = "bottom"))
update_geom_defaults("line", list(linewidth = 2))
update_geom_defaults("point", list(size = 4))

  
# plot safety vs non-safety acceptance rate over time
df %>%
  select(year, safety_acc_pct, nonsafety_acc_pct) %>%
  pivot_longer(c(safety_acc_pct, nonsafety_acc_pct),
               names_to = "group", values_to = "acc_pct") %>%
  mutate(
    group = recode(group,
      safety_acc_pct    = "Safety",
      nonsafety_acc_pct = "Non-Safety"
    )
  ) %>%
  ggplot(aes(x = year, y = acc_pct, color = group)) +
  geom_line() +
  geom_point() +
  scale_y_continuous(labels = scales::percent_format(scale = 1)) +
  labs(
    x = "Year", y = "Acceptance Rate (%)", color = NULL
  )

ggsave(here("output_data/analysis/iclr_acceptance/safety_acceptance.pdf"),
       width = 12, height = 10)

# ---- linear probability model: does safety predict acceptance? ----
# uses paper-level `papers` df; accepted is 0/1 outcome
mod_acc <- lm(as.integer(accepted) ~ safety + year, data = papers)

robust_stargazer(mod_acc,
  output  = "acceptance_regression.html",
  dep_var = "Accepted",
  co_var  = c("Safety Paper", "Year"),
  in_main_paper = TRUE)

# ---- Per-year linear models with measurement error bootstrap ----

# helper: fits accepted ~ safety for a given dataset and characterizes the
# uncertainty from classifier error by randomly flipping each label at rate
# safety_error_rate and re-estimating.
#
# Random label flipping attenuates the coefficient toward zero, so the simulation
# is used only for its spread (a measurement-error variability band), which is
# then recentered on the observed point estimate. Returns the point estimate and
# that re-anchored 95% band; if safety_error_rate is NA, band columns are returned as NA.
bootstrap_coef <- function(data, n_sim = 1000) {
  m         <- lm(as.integer(accepted) ~ safety, data = data)
  point_est <- unname(coef(m)[2])
  p_value   <- unname(summary(m)$coefficients[2, 4])

  if (is.na(safety_error_rate)) {
    return(tibble(coef = point_est, p_value = p_value,
                  ci_low = NA_real_, ci_high = NA_real_))
  }

  sim_coefs <- replicate(n_sim, {
    data_sim <- data %>%
      mutate(safety = if_else(
        runif(n()) < safety_error_rate, !as.logical(safety), as.logical(safety)
      ))
    unname(coef(lm(as.integer(accepted) ~ safety, data = data_sim))[2])
  })

  # re-anchor the simulated spread on the observed estimate: take the simulation's
  # 2.5/97.5 quantiles relative to its own median, then offset from point_est.
  # removes the attenuation shift so the band always brackets the point estimate.
  q   <- quantile(sim_coefs, c(0.025, 0.975), na.rm = TRUE)
  med <- median(sim_coefs, na.rm = TRUE)

  tibble(
    coef    = point_est,
    p_value = p_value,
    ci_low  = point_est + (q[1] - med),
    ci_high = point_est + (q[2] - med)
  )
}

# group by year, apply bootstrap_coef to each group
set.seed(42)
year_results <- papers %>%
  group_by(year) %>%
  group_modify(~ bootstrap_coef(.x)) %>%
  ungroup()

stargazer(as.data.frame(year_results),
  summary  = FALSE,
  rownames = FALSE,
  digits   = 4,
  title    = "Per-Year Safety Acceptance Coefficients with Bootstrap CI",
  type     = "html",
  out      = here("output_data/analysis/iclr_acceptance/acceptance_by_year.html"))

# build x-axis labels: append * to years significant at p < 0.05
year_labels <- ifelse(
  year_results$p_value < 0.05,
  paste0(year_results$year, "*"),
  as.character(year_results$year)
)

# plot: coefficient over time. The line/points are the observed per-year
# coefficients; the ribbon is the classifier-error sensitivity band, which is
# re-anchored on each point estimate in bootstrap_coef() so it brackets the line
# by construction (see the note there on attenuation bias).
ggplot(year_results, aes(x = year, y = coef)) +
  geom_ribbon(aes(ymin = ci_low, ymax = ci_high), alpha = 0.15, fill = "steelblue") +
  geom_hline(yintercept = 0, linetype = "dashed", color = "gray50") +
  geom_line(color = "steelblue") +
  geom_point(color = "steelblue") +
  scale_x_continuous(breaks = year_results$year, labels = year_labels) +
  labs(x = "Year", y = "Coeff. (Safety on Acceptance)")

ggsave(here("output_data/analysis/iclr_acceptance/acceptance_by_year.pdf"), width = 12, height = 10)
ggsave(here("paper_figures/acceptance_by_year.pdf"), width = 12, height = 10)


# ---- Withdrawn papers: re-run the acceptance LPM including withdrawn submissions ----
# papers_withdrawn adds the withdrawn pile (treated as not accepted) on top of the
# accepted + rejected papers used above, so we can see whether counting withdrawn
# submissions as non-accepted changes the safety/acceptance relationship.
withdrawn <- read_csv(here("output_data/classifiers/iclr-withdrawn-classified.csv")) %>%
  mutate(uid = as.character(uid), accepted = FALSE, withdrawn = TRUE)

papers_withdrawn <- bind_rows(papers, withdrawn)

mod_acc_withdrawn <- lm(as.integer(accepted) ~ safety + year, data = papers_withdrawn)

robust_stargazer(mod_acc_withdrawn,
  output  = "acceptance_regression_withdrawn.html",
  dep_var = "Accepted",
  co_var  = c("Safety Paper", "Year"),
  in_appendix = TRUE)