#SetUp
library(here)
library(tidyverse)   
library(scales)      
library(broom)       

# clean env
rm(list = ls())

df <- read_csv(here("output_data/classifiers/abstracts-classified.csv"))

# output directory for co-occurrence plots & tables
out_dir <- here("output_data", "analysis", "co-occurrence")


category_labels <- c(
  indiv_grp_harm = "Individual/Group Harm",
  info_epistemic_harm = "Info & Epistemic Harm",
  socioec_harm = "Socioeconomic Harm",
  physical_harm = "Physical Harm",
  abstract_harm = "Abstract Harm",
  reliability_safety = "Reliability & Robustness",
  bias_inequity = "Bias & Inequity",
  security_resilience = "Security & Resilience",
  transparency_accountability = "Transparency & Accountability",
  alignment = "Alignment",
  governance = "Governance"
)

col_names <- c(
  "indiv_grp_harm",
  "info_epistemic_harm",
  "socioec_harm",
  "physical_harm",
  "abstract_harm",
  "reliability_safety",
  "bias_inequity",
  "security_resilience",
  "transparency_accountability",
  "alignment",
  "governance"
)

# shared color palette, keyed by display label (matches analysis_safety.R /
# analysis_acceptance.R so each category keeps the same color across all scripts)
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

# shared plot theme (matches the other analysis scripts)
windowsFonts(Times = windowsFont("Times New Roman"))
theme_set(theme_minimal(base_size = 34, base_family = "Times") +
  theme(legend.position = "bottom"))
update_geom_defaults("line", list(linewidth = 2))
update_geom_defaults("point", list(size = 4))

#Function

cooccurance <- function(safety_df, focus_cat, col_names, category_labels,
                        save_plot = FALSE, save_table = FALSE) {
  
  #calculates for every year, the % of focus_cat papers also classified 
  #as pair_cat, we also got rid of every year with <10 papers 
  
  category_time <- map_dfr(col_names, function(pair_cat) {
    safety_df %>%
      mutate(across(all_of(c(focus_cat, pair_cat)), ~ replace_na(as.logical(.x), FALSE))) %>%
      group_by(year) %>%
      summarise(
        focus_n = sum(.data[[focus_cat]], na.rm = TRUE),
        both_n = sum(.data[[focus_cat]] & .data[[pair_cat]], na.rm = TRUE),
        pct_cooccurring = ifelse(focus_n > 0, both_n / focus_n, NA_real_),
        .groups = "drop"
      ) %>%
      mutate(
        paired_category = pair_cat,
        se = sqrt(pct_cooccurring * (1 - pct_cooccurring) / focus_n),
        ci_lower = pmax(0, pct_cooccurring - 1.96 * se),
        ci_upper = pmin(1, pct_cooccurring + 1.96 * se)
      )
  }) %>%
    filter(
      paired_category != focus_cat,
      focus_n >= 10
    ) %>%
    mutate(
      paired_category_raw = paired_category,
      paired_category = recode(paired_category, !!!category_labels)
    )
  
  
  # year-trend logistic regression for each paired category
  trend_tests <- category_time %>%
    group_by(paired_category, paired_category_raw) %>%
    group_modify(~ {
      model <- glm(
        cbind(both_n, focus_n - both_n) ~ year,
        family = binomial,
        data = .x
      )
      broom::tidy(model) %>%
        filter(term == "year") %>%
        mutate(
          direction = ifelse(estimate > 0, "increasing", "decreasing"),
          significant = p.value < 0.05
        )
    }) %>%
    ungroup()

  cooccurrence_plot <- ggplot(
    category_time,
    aes(x = year, y = pct_cooccurring, color = paired_category, fill = paired_category)
  ) +
    geom_ribbon(aes(ymin = ci_lower, ymax = ci_upper), alpha = 0.15, color = NA) +
    geom_line() +
    geom_point() +
    scale_y_continuous(labels = percent_format(accuracy = 1)) +
    scale_x_continuous(breaks = scales::breaks_width(1)) +
    scale_color_manual(values = category_colors) +
    scale_fill_manual(values = category_colors) +
    labs(
      x = "Year",
      y = "Co-Occurrence Rate",
      color = "Category",
      fill = "Category"
    ) +
    guides(color = guide_legend(ncol = 2), fill = "none") +
    theme(legend.justification = "right")
  
  conditional_table <- safety_df %>%
    mutate(across(all_of(col_names), ~ replace_na(as.logical(.x), FALSE))) %>%
    group_by(year) %>%
    summarise(
      focus_n = sum(.data[[focus_cat]], na.rm = TRUE),
      across(
        all_of(col_names),
        ~ ifelse(
          focus_n > 0,
          sum(.data[[focus_cat]] & .x, na.rm = TRUE) / focus_n,
          NA_real_
        ),
        .names = "{.col}"
      ),
      .groups = "drop"
    ) %>%
    filter(focus_n >= 10) %>% #we filtered for the amount of papers less than 10 to not mess up graphs
    select(-all_of(focus_cat)) %>%
    mutate(
      across(all_of(setdiff(col_names, focus_cat)), ~ percent(.x, accuracy = 0.1))
    ) %>%
    rename_with(~ recode(.x, !!!category_labels), any_of(setdiff(col_names, focus_cat))) %>%
    arrange(year)
  
  if (save_plot) {
    ggsave(
      filename = file.path(out_dir, paste0(focus_cat, "_cooccurrence.pdf")),
      plot = cooccurrence_plot,
      width = 12, height = 10
    )
  }
  
  if (save_table) {
    write_csv(conditional_table, file.path(out_dir, paste0(focus_cat, "_cooccurrence_table.csv")))
  }
  
  list(
    plot = cooccurrence_plot,
    table = conditional_table,
    trend_tests = trend_tests,
    data = category_time
  )
}

#Running all Relationships

all_cooc_results <- col_names %>%
  set_names() %>%
  map(~ cooccurance(df, .x, col_names, category_labels, save_plot = TRUE, save_table = TRUE))

#all cooc results pairs are in the results, to call different things, use this.

all_cooc_results$socioec_harm$plot

#all_cooc_results$alignment$plot          # the ggplot object
#all_cooc_results$alignment$table         # the formatted table 
#all_cooc_results$alignment$trend_tests   # the year-trend regression results


all_cooc_results$socioec_harm$plot