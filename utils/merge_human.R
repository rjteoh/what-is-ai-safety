# merge_human.R
#
# Short script to merge the raw human inputs from our three student coders
# (Ella, Tyler, RJ) via majority voting. It produces two outputs:
#   - human_raw.csv:     the merged document showing all the categories the
#                        coders agreed on (after voting).
#   - human_disagree.csv: a separate CSV listing the rows where the coders
#                         disagreed.
# The thresholds for agreement/disagreement are set in the global variables
# `safety_vote` (minimum votes to flag the safety column) and `cat_vote`
# (minimum votes to flag a category column).

# Load required libraries
library(tidyverse)
library(caret)
library(irr)
library(here)

rm(list = ls()) # clean env

safety_vote <- 3 # minimum votes for positive case (safety)
cat_vote <- 2 # minimum votes for positive case (category)

# reading csv files
df1 <- read_csv(here("input_data", "test_data",  "raw_coder_data", "coder_1.csv"), show_col_types = FALSE)
df2 <- read_csv(here("input_data", "test_data",  "raw_coder_data", "coder_2.csv"), show_col_types = FALSE)
df3 <- read_csv(here("input_data", "test_data",  "raw_coder_data", "coder_3.csv"), show_col_types = FALSE)

# Define the columns that need majority voting
voting_cols <- c("safety", "indiv_grp_harm", "info_epistemic_harm", "socioec_harm", 
                 "physical_harm", "abstract_harm", "reliability_safety", "bias_inequity", 
                 "security_resilience", "transparency_accountability", "alignment", "governance")
cat_cols <- setdiff(voting_cols, "safety")

# Create df with vote sums and identify disagreement rows
vote_sums <- df1 %>%
  mutate(
    across(
      .cols = all_of(voting_cols),
      .fns = ~ df1[[cur_column()]] + df2[[cur_column()]] + df3[[cur_column()]],
      .names = "{.col}"
    )
  )

# Export rows where at least one column has disagreement (sum is 1 or 2)
disagree <- vote_sums %>%
  filter(if_any(all_of(voting_cols), ~ .x == 1 | .x == 2))

write_csv(disagree, here("utils", "human_disagree.csv"))

# create a merged df with the results of the human majority voting
human_raw <- df1 %>%
  mutate(
    # calculate votes for safety column (stricter criteria)
    safety = if_else((df1[["safety"]] + df2[["safety"]] +
                        df3[["safety"]]) >= safety_vote, 1, 0),
    # calculate votes for category column (softer criteria)
    across(
      .cols = all_of(cat_cols),
      .fns = ~ if_else((df1[[cur_column()]] + df2[[cur_column()]] +
                          df3[[cur_column()]]) >= cat_vote, 1, 0),
      .names = "{.col}"
    )
  )

# save merged df
write_csv(human_raw, here("utils", "human_raw.csv"))