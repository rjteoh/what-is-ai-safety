# analysis_safety.R
#
# Relates safety research output to big-tech sponsorship across five conferences 
# (NeurIPS, ICML, ICLR, NAACL, FAccT). It combines the classified abstracts 
# (abstracts-classified.csv) with the classified sponsor list (sponsors-classified.csv) 
# into a conference x year panel, then:
#   - builds per-conference-year safety rates (% of papers) and per-category rates
#     (% of safety papers), alongside big-tech sponsor shares (all and top-tier)
#   - fits two-way (conference + year) fixed-effects panel regressions of the safety
#     rate on big-tech share, plus per-conference OLS, with robust/clustered SEs
#   - repeats the panel regressions for each of the 11 safety categories
#   - runs a conference-fixed-effects LPM of the safety flag to compare conferences
#   - plots safety and category trends over time (with a classifier-error band)
#   - writes year x conference appendix tables for safety and each category
#
# Key inputs:
#   - output_data/classifiers/abstracts-classified.csv : per-paper safety + category
#     labels (booleans written as "True"/"False" strings)
#   - output_data/classifiers/sponsors-classified.csv  : per-sponsor tier + big-tech flag
#
# Outputs:
#   - HTML tables / CSVs / PDFs -> output_data/analysis/safety_trends/ (for browsing & debugging)
#   - LaTeX copies of paper figures -> paper_figures/ (main paper) and
#     paper_figures/appendix/ (appendix tables)
#
# Uncertainty bands: safety_error_rate and cat_error_rate are the classifier's
# estimated misclassification rates (from the June 22 robustness run) used to draw
# +/- error ribbons on the trend plots. Set either to NA to suppress its band.
#
# Robust standard errors: every table's SEs are computed in the robust_stargazer()
# helper below (the se_list block). That is the single place to edit if you want a
# different robust SE type (e.g. a different vcovHC `type`, or another clustering).
#
# Naming note: the variable/column `reliability_safety` is a legacy name kept for
# backwards compatibility across the pipeline. The intended (display) name for this
# category is "Reliability & Robustness" -- that is what is printed in graphs and tables.
#
# Usage: run end-to-end in R/RStudio (uses here() for repo-root-relative paths).

library(here)
library(tidyverse)
library(plm)
library(lmtest)
library(sandwich)  # vcovHC for robust/clustered SEs
library(stargazer)
library(ggbreak)
library(xtable)


# clean env and set working directory
rm(list = ls())

# Estimated misclassification rate of the paper classifier based on
# tests from June 22 (0–1).
# Set to NA to suppress uncertainty indications
safety_error_rate <- 0.1549
cat_error_rate <- 0.20

# import data
sponsors <- read.csv(here("output_data", "classifiers", "sponsors-classified.csv"))
safety_raw <- read.csv(here("output_data", "classifiers", "abstracts-classified.csv"))

# setting sponsor tier definitions
all_tiers <- c("platinum", "diamond", "gold", "silver", "bronze", "ruby",
               "sapphire", "exhibitor", "supporting", "sponsors", "supporters")
top_tiers <- c("platinum", "diamond", "ruby", "sapphire", "sponsors")

# defining safety category columns
safety_cols <- c("indiv_grp_harm", "info_epistemic_harm", "socioec_harm",
                 "physical_harm", "abstract_harm", "reliability_safety",
                 "bias_inequity", "security_resilience",
                 "transparency_accountability", "alignment", "governance")

# the classifier writes booleans as "True"/"False" strings, which read.csv loads
# as character; coerce all classification columns to logical so sum() etc. work
class_cols <- c("safety", safety_cols)
safety_raw <- safety_raw %>%
  mutate(across(all_of(class_cols), as.logical))


# writing a helper function to use stargazer with robust ses
# NOTE: I used stargazer because that was what I was taught to use,
# but frankly it breaks a lot and I have discovered that the library
# is no longer being actively mantained. Switching to modelsummary
# might be better for project replicability and longevity
robust_stargazer <- function(..., output, dep_var = NULL, co_var = NULL,
                            column.labels = NULL, column.separate = NULL,
                            dep_var_include = TRUE, in_main_paper = FALSE,
                            in_appendix = FALSE,
                            omit = NULL, add.lines = NULL, notes = NULL) {
  models <- list(...)
  # Calculate robust SEs. This is THE place to change the robust SE type used
  # throughout this script: panel (plm) models get cluster-robust HC1 SEs
  # clustered by group (conference), plain lm models get heteroskedasticity-robust
  # HC1 SEs. To switch estimator, edit the vcovHC `type`/`cluster` args below.
  se_list <- lapply(models, function(model) {
    if (inherits(model, "plm")) {
      sqrt(diag(vcovHC(model, type = "HC1", cluster = "group")))  # clustered for panel lm
    } else {
      sqrt(diag(vcovHC(model, type = "HC1")))  # no clustering for lm
    }
  })

  # Always write the HTML table to the main analysis output folder. Optionally also
  # write a LaTeX copy: main-paper tables go to the project-root paper_figures/
  # folder, appendix tables to paper_figures/appendix/ (one home for every paper
  # figure). stargazer picks the format per file from its extension.
  out_paths <- here("output_data", "analysis", "safety_trends", output)
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

# ---- 1. Data Cleaning and Construction ----

# calculate safety and category statistics from classified abstracts
safety <- safety_raw %>%
  group_by(year, conference) %>%
  summarize(
    paper_n = n(),
    safety_n = sum(safety, na.rm = TRUE),
    safety_pct = safety_n / paper_n * 100,
    across(
      all_of(safety_cols),
      list(
        n = \(x) sum(x, na.rm = TRUE),
        pct   = \(x) sum(x, na.rm = TRUE) / sum(safety, na.rm = TRUE) * 100
      ),
      .names = "{.col}_{.fn}"
    )
  )

# last mile cleaning
sponsors <- sponsors %>%
  mutate(
    tier = str_to_lower(tier), # converting all to lowercase
    tier = word(tier, 1), # taking just the first word for easier parsing
    is_bigtech = as.logical(is_bigtech), # "True"/"False" strings -> logical
  ) %>%
  filter(
    tier %in% all_tiers # only keeping selected sponsor tiers
  )

# calculate bigtech stats across all and top-tier sponsors
sponsors <- sponsors %>%
  group_by(conference, year) %>%
  summarize(
    total_sponsors  = n(),
    bigtech_n       = sum(is_bigtech, na.rm = TRUE),
    bigtech_pct     = bigtech_n / total_sponsors * 100,
    total_toptier   = sum(tier %in% top_tiers, na.rm = TRUE),
    bigtech_top_n   = sum(is_bigtech * (tier %in% top_tiers)),
    bigtech_top_pct = bigtech_top_n / total_toptier * 100
  ) %>%
  # replaces NAs in numeric columns
  mutate(across(where(is.numeric), ~replace_na(., 0)))

# combine with safety data and export to csv for easier debugging
df <- left_join(
  safety, sponsors, by = c("year", "conference")
) %>%
  # NAACL 2015 and 2016 are missing abstracts so we drop them
  filter(!(conference == "naacl" & year %in% c(2015, 2016)))

write.csv(df, file = here("output_data", "analysis", "safety_trends","df.csv"), row.names = FALSE)

# ---- 2. Panel regression with Two-way Fixed Effects ----

# convert to panel data
df_panel <- pdata.frame(df, index = c("conference", "year"))

mod1 <- plm(
  safety_pct ~ bigtech_pct,
  data = df_panel,
  effect = "twoway",
  model = "within"
)
coeftest(mod1, vcov = vcovHC(mod1, type = "HC1", cluster = "group"))

# running conference level regressions
m1_nrp <- lm(safety_pct ~ bigtech_pct,
                   data = df %>% filter(conference == "neurips"))
m1_icml <- lm(safety_pct ~ bigtech_pct,
                data = df %>% filter(conference == "icml"))
m1_iclr <- lm(safety_pct ~ bigtech_pct,
                data = df %>% filter(conference == "iclr"))
m1_naacl <- lm(safety_pct ~ bigtech_pct,
                 data = df %>% filter(conference == "naacl"))
m1_facct <- lm(safety_pct ~ bigtech_pct,
                 data = df %>% filter(conference == "facct"))

# exporting in stargazer (this goes in main paper)
robust_stargazer(mod1,
                 output = "safety_allsponsors.html",
                 dep_var = "\\% of safety papers",
                 co_var = "\\% of 'big tech' sponsors",
                 in_main_paper = TRUE)
# conference by conference comparison (appendix). Split 2-3 across two tables so
# it fits the page width in the paper.
robust_stargazer(m1_nrp, m1_icml,
                 output = "safety_allsponsors_byconference_1.html",
                 dep_var = "\\% of safety papers",
                 co_var = "\\% of 'big tech' sponsors",
                 column.labels = c("NeurIPS", "ICML"),
                 column.separate = c(1, 1),
                 in_appendix = TRUE)
robust_stargazer(m1_iclr, m1_naacl, m1_facct,
                 output = "safety_allsponsors_byconference_2.html",
                 dep_var = "\\% of safety papers",
                 co_var = "\\% of 'big tech' sponsors",
                 column.labels = c("ICLR", "NAACL", "FAccT"),
                 column.separate = c(1, 1, 1),
                 in_appendix = TRUE)

# stitch the two split LaTeX tables into one file for easy copy-paste into the
# paper (they stay separate table environments; this just concatenates them).
# Done as a post-step so robust_stargazer() itself is untouched.
appendix_dir <- here("paper_figures", "appendix")
byconf_parts <- file.path(appendix_dir,
                          c("safety_allsponsors_byconference_1.tex",
                            "safety_allsponsors_byconference_2.tex"))
writeLines(
  unlist(lapply(byconf_parts, function(f) c(readLines(f), ""))),
  file.path(appendix_dir, "safety_allsponsors_byconference.tex")
)
file.remove(byconf_parts)  # keep only the combined .tex (HTML copies remain for browsing)

### ---- 2.1 Panel regression with Two-way Fixed Effects [Category] ----

# coding a helper function that makes models for each category and
# outputs in nice format as stargazer with robust SEs
category_stargazer <- function(data, indep, output, co_var) {
  formula <- function(dep) as.formula(paste(dep, "~", indep))
  m3a <- plm(formula("indiv_grp_harm_pct"), data = data, effect = "twoway", model = "within")
  m3b <- plm(formula("info_epistemic_harm_pct"), data = data, effect = "twoway", model = "within")
  m3c <- plm(formula("socioec_harm_pct"), data = data, effect = "twoway", model = "within")
  m3d <- plm(formula("physical_harm_pct"), data = data, effect = "twoway", model = "within")
  m3e <- plm(formula("abstract_harm_pct"), data = data, effect = "twoway", model = "within")
  m3f <- plm(formula("reliability_safety_pct"), data = data, effect = "twoway", model = "within")
  m3g <- plm(formula("bias_inequity_pct"), data = data, effect = "twoway", model = "within")
  m3h <- plm(formula("security_resilience_pct"), data = data, effect = "twoway", model = "within")
  m3i <- plm(formula("transparency_accountability_pct"), data = data, effect = "twoway", model = "within")
  m3j <- plm(formula("alignment_pct"), data = data, effect = "twoway", model = "within")
  m3k <- plm(formula("governance_pct"), data = data, effect = "twoway", model = "within")
  robust_stargazer(
    m3a, m3b, m3c, m3d, m3e, m3f, m3g, m3h, m3i, m3j, m3k,
    output = output,
    co_var = co_var,
    column.labels = c("Indiv/Grp", "Info + Epist", "Socioec",
                      "Physical", "Abstract", "Reliability + Robustness",
                      "Bias + Inequity", "Security", "Transparency", "Alignment", "Governance"),
    column.separate = rep(1, 11),
    dep_var_include = FALSE
  )
}

# top sponsors and all sponsors with inclusive data
category_stargazer(df_panel, "bigtech_pct",
                   output = "cat_all.html",
                   co_var = "\\% of 'big tech' sponsors")

category_stargazer(df_panel, "bigtech_top_pct",
                   output = "cat_top.html",
                   co_var = "\\% of 'big tech' top-tier sponsors")


# ---- 3. Misc Models ---
## ---- 3.1 Checking Conference Relation to Safety Output ----
# set NeurIPS as reference conference
safety_raw <- safety_raw %>%
  mutate(conference = relevel(as.factor(conference), ref = "neurips"))
mod4 <- lm(safety ~ conference + as.factor(year), data = safety_raw)
coeftest(mod4, vcov = vcovHC(mod4, type = "HC1"))
# HTML copy to the main analysis output folder (for readable browsing) plus a
# LaTeX copy to paper_figures/appendix/ (this is an appendix table, not a
# main-paper figure)
robust_stargazer(mod4,
                 output = "safetybyconference.html",
                 dep_var = "Pr(Safety Paper)",
                 co_var = c("FAccT", "ICML", "ICLR", "NAACL", "Constant"),
                 omit = "year",
                 add.lines = list(c("Year FE", "Yes")),
                 notes = "Reference conference: NeurIPS.",
                 in_appendix = TRUE)


# ---- 4. Graphing ----

# theme package
windowsFonts(Times = windowsFont("Times New Roman"))
theme_set(theme_minimal(base_size = 34, base_family = "Times") +
  theme(legend.position = "bottom"))
update_geom_defaults("line", list(linewidth = 2))
update_geom_defaults("point", list(size = 4))

# defining category labels and colors
category_labels <- c(
  indiv_grp_harm           = "Individual/Group Harm",
  info_epistemic_harm      = "Info & Epistemic Harm",
  socioec_harm             = "Socioeconomic Harm",
  physical_harm            = "Physical Harm",
  abstract_harm            = "Abstract Harm",
  reliability_safety       = "Reliability & Robustness",
  bias_inequity            = "Bias & Inequity",
  security_resilience      = "Security & Resilience",
  transparency_accountability = "Transparency & Accountability",
  alignment                = "Alignment",
  governance               = "Governance"
)

category_colors <- c(
  "Individual/Group Harm"         = "#E41A1C",
  "Info & Epistemic Harm"         = "#377EB8",
  "Socioeconomic Harm"            = "#4DAF4A",
  "Physical Harm"                 = "#984EA3",
  "Abstract Harm"                 = "#FF7F00",
  "Reliability & Robustness"      = "#A65628",
  "Bias & Inequity"               = "#F781BF",
  "Security & Resilience"         = "#1B9E77",
  "Transparency & Accountability" = "#D95F02",
  "Alignment"                     = "#7570B3",
  "Governance"                    = "#E6AB02"
)

# safety_pct over time by conference
p_safety <- ggplot(df, aes(x = year, y = safety_pct,
               color = conference, group = conference)) +
  {if (!is.na(safety_error_rate))
    geom_ribbon(aes(ymin = safety_pct * (1 - safety_error_rate),
                    # cap the upper error band at 100% (it's a percentage)
                    ymax = pmin(safety_pct * (1 + safety_error_rate), 100),
                    fill = conference),
                alpha = 0.15, color = NA, show.legend = FALSE)} +
  geom_line() +
  geom_point() +
  labs(
    x = "Year",
    y = "% of Total Output",
    color = "Conference"
  ) +
  scale_x_continuous(breaks = scales::breaks_width(1)) +
  # cap the y axis at 100% (set before scale_y_break, as ggbreak expects)
  scale_y_continuous(limits = c(0, 100)) +
  scale_color_discrete(
    labels = c("iclr" = "ICLR", "icml" = "ICML",
               "naacl" = "NAACL", "neurips" = "NeurIPS",
               "facct" = "FAccT")
  ) +
  guides(color = guide_legend(nrow = 2)) +
  theme(
    axis.text.x.top = element_blank(),
    axis.ticks.x.top = element_blank(),
    axis.line.x.top = element_blank()
  ) +
  scale_y_break(c(35, 70), space = 1)

# NOTE: scale_y_break() makes p_safety a `ggbreak` object whose print method calls
# grid.newpage(), so the saved PDF has a blank leading page (the plot is on page 2).
# This is a known ggbreak quirk; flattening it away (e.g. ggplotify::as.ggplot) drops
# the axis break, so we keep the break and just discard the blank page downstream.
ggsave(here("output_data", "analysis", "safety_trends","safety_trends.pdf"), plot = p_safety, width = 12, height = 10)
ggsave(here("paper_figures", "safety_trends.pdf"), plot = p_safety, width = 12, height = 10)

# category trends over time (aggregated across all conferences)
category_trends <- df %>%
  group_by(year) %>%
  summarize(
    safety_n = sum(safety_n, na.rm = TRUE),
    across(all_of(paste0(safety_cols, "_n")), \(x) sum(x, na.rm = TRUE))
  ) %>%
  pivot_longer(
    cols = all_of(paste0(safety_cols, "_n")),
    names_to = "category",
    values_to = "n"
  ) %>%
  mutate(
    pct = n / safety_n * 100,
    category = recode(str_remove(category, "_n$"), !!!category_labels)
  )

harm_labels <- c("Individual/Group Harm", "Info & Epistemic Harm",
                  "Socioeconomic Harm", "Physical Harm", "Abstract Harm")
issue_labels <- c("Reliability & Robustness", "Bias & Inequity", "Security & Resilience",
                  "Transparency & Accountability", "Alignment", "Governance")

harm_trends  <- category_trends %>% filter(category %in% harm_labels)
issue_trends <- category_trends %>% filter(category %in% issue_labels)

# harm areas - pct
ggplot(harm_trends, aes(x = year, y = pct, color = category, group = category)) +
  {if (!is.na(cat_error_rate))
    geom_ribbon(aes(ymin = pct * (1 - cat_error_rate),
                    ymax = pct * (1 + cat_error_rate),
                    fill = category),
                alpha = 0.15, color = NA, show.legend = FALSE)} +
  geom_line() +
  geom_point() +
  labs(
    x = "Year",
    y = "% of Safety Papers",
    color = "Category"
  ) +
  scale_x_continuous(breaks = scales::breaks_width(1)) +
  scale_color_manual(values = category_colors) +
  scale_fill_manual(values = category_colors) +
  guides(color = guide_legend(nrow = 3))

ggsave(here("output_data", "analysis", "safety_trends","category_trends_harm_pct.pdf"), width = 12, height = 10)
ggsave(here("paper_figures", "category_trends_harm_pct.pdf"), width = 12, height = 10)


# issue areas - pct
ggplot(issue_trends, aes(x = year, y = pct, color = category, group = category)) +
  {if (!is.na(cat_error_rate))
    geom_ribbon(aes(ymin = pct * (1 - cat_error_rate),
                    ymax = pct * (1 + cat_error_rate),
                    fill = category),
                alpha = 0.15, color = NA, show.legend = FALSE)} +
  geom_line() +
  geom_point() +
  labs(
    x = "Year",
    y = "% of Safety Papers",
    color = "Category"
  ) +
  scale_x_continuous(breaks = scales::breaks_width(1)) +
  scale_color_manual(values = category_colors) +
  scale_fill_manual(values = category_colors) +
  guides(color = guide_legend(nrow = 3))

ggsave(here("output_data", "analysis", "safety_trends","category_trends_issue_pct.pdf"), width = 12, height = 10)
ggsave(here("paper_figures", "category_trends_issue_pct.pdf"), width = 12, height = 10)

# harm areas - raw count
ggplot(harm_trends, aes(x = year, y = n, color = category, group = category)) +
  {if (!is.na(cat_error_rate))
    geom_ribbon(aes(ymin = n * (1 - cat_error_rate),
                    ymax = n * (1 + cat_error_rate),
                    fill = category),
                alpha = 0.15, color = NA, show.legend = FALSE)} +
  geom_line() +
  geom_point() +
  labs(
    x = "Year",
    y = "Number of Papers",
    color = "Category"
  ) +
  scale_x_continuous(breaks = scales::breaks_width(1)) +
  scale_color_manual(values = category_colors) +
  scale_fill_manual(values = category_colors) +
  guides(color = guide_legend(nrow = 3))

ggsave(here("output_data", "analysis", "safety_trends","category_trends_harm_n.pdf"), width = 12, height = 10)

# issue areas - raw count
ggplot(issue_trends, aes(x = year, y = n, color = category, group = category)) +
  {if (!is.na(cat_error_rate))
    geom_ribbon(aes(ymin = n * (1 - cat_error_rate),
                    ymax = n * (1 + cat_error_rate),
                    fill = category),
                alpha = 0.15, color = NA, show.legend = FALSE)} +
  geom_line() +
  geom_point() +
  labs(
    x = "Year",
    y = "Number of Papers",
    color = "Category"
  ) +
  scale_x_continuous(breaks = scales::breaks_width(1)) +
  scale_color_manual(values = category_colors) +
  scale_fill_manual(values = category_colors) +
  guides(color = guide_legend(nrow = 3))

ggsave(here("output_data", "analysis", "safety_trends","category_trends_issue_n.pdf"), width = 12, height = 10)

# export to csv for easier checks
category_trends <- category_trends %>%
  pivot_wider(
    id_cols = year,
    names_from = category,
    values_from = pct
  )

write.csv(category_trends, file = here("output_data", "analysis", "safety_trends", "category_trends.csv"), row.names = FALSE)

# ---- 5. Appendix Tables ----
# making safety and category x conference tables for the main paper appendix.
# Every table is a year x conference grid of percentages; to keep the appendix
# tidy we append them all into a single HTML file (for browsing) and a single
# LaTeX file (for the paper) rather than writing one file per category.

conf_labels <- c(iclr = "ICLR", icml = "ICML", naacl = "NAACL",
                  neurips = "NeurIPS", facct = "FAccT")
conf_order <- names(conf_labels)

main_dir  <- here("output_data", "analysis", "safety_trends")  # HTML copy, for readability
paper_dir <- here("paper_figures", "appendix")        # LaTeX copy, for the paper appendix

# combined output files: all tables are appended into one of each
html_out  <- file.path(main_dir,  "summary_appendix.html")
latex_out <- file.path(paper_dir, "summary_appendix.tex")
# start fresh so re-runs don't append onto stale content
if (file.exists(html_out))  file.remove(html_out)
if (file.exists(latex_out)) file.remove(latex_out)

# helper: build a year x conference table of % for a given column and append it
# to the combined HTML table (main output folder, for easy browsing) and the
# combined LaTeX table (paper_figures/appendix/, for the paper). A trailing "All"
# column gives the global figure across all 5 conferences for each year, computed
# as the pooled rate (summed num_col / summed den_col), NOT a mean of the
# per-conference percentages, so it stays correctly weighted by conference size.
make_appendix_table <- function(data, value_col, num_col, den_col, caption, label) {
  wide <- data %>%
    select(year, conference, value = all_of(value_col)) %>%
    mutate(
      conference = factor(conference, levels = conf_order, labels = conf_labels[conf_order]),
      value = ifelse(is.nan(value), NA, round(value, 1))
    ) %>%
    pivot_wider(id_cols = year, names_from = conference, values_from = value) %>%
    arrange(year)

  # global ("All") column: pooled rate across all conferences present in each year
  global <- data %>%
    group_by(year) %>%
    summarize(
      All = sum(.data[[num_col]], na.rm = TRUE) / sum(.data[[den_col]], na.rm = TRUE) * 100,
      .groups = "drop"
    ) %>%
    mutate(All = ifelse(is.nan(All), NA, round(All, 1)))

  wide <- wide %>%
    left_join(global, by = "year") %>%
    relocate(All, .after = year) %>%  # global column first, before the conferences
    rename(Year = year)  # capitalize the column header in the rendered tables

  xt <- xtable(wide, caption = caption, label = label, digits = 1)

  # HTML -> combined file in the main analysis output folder; raw & is fine.
  # caption.placement = "top" puts the table title above the table rather than below.
  print(xt, type = "html", include.rownames = FALSE, NA.string = "--",
        caption.placement = "top", file = html_out, append = TRUE)

  # LaTeX -> combined file in paper_figures/appendix/ (escape & in the caption; xtable doesn't).
  # caption.placement = "top" puts the table title above the table rather than below.
  attr(xt, "caption") <- gsub("&", "\\\\&", caption)
  print(xt, type = "latex", include.rownames = FALSE, NA.string = "--",
        caption.placement = "top", file = latex_out, append = TRUE)
}

# top-level safety category (% of all papers)
make_appendix_table(
  df, "safety_pct", num_col = "safety_n", den_col = "paper_n",
  caption = "Percentage of Papers Classified as Safety-Related, by Conference and Year",
  label = "tab:summary_safety"
)

# harm/issue subcategories (% of safety papers)
for (cat in safety_cols) {
  make_appendix_table(
    df, paste0(cat, "_pct"), num_col = paste0(cat, "_n"), den_col = "safety_n",
    caption = paste0("Percentage of Safety Papers Classified as ",
                      category_labels[[cat]], ", by Conference and Year"),
    label = paste0("tab:summary_", cat)
  )
}
