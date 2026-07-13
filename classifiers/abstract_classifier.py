"""
Abstract classifier: takes the combined abstracts CSV produced by the paper
scraper and labels each paper for AI-safety relevance, then sorts the safety
papers into one or more harm/safety categories — using an LLM in two passes.

What it does:
    1. Loads the scraped abstracts and strips the held-out test set in-memory
       (see utils/remove_test_abstracts.py) so it never leaks into the classified
       pile. (--test skips this step and classifies the test set itself.)
    2. First pass: classifies every abstract as safety-relevant (TRUE/FALSE).
    3. Second pass: for the safety==TRUE rows only, runs one classification per
       category in the prompt set, producing one-hot category columns.
    4. Writes results incrementally, INTERVAL rows at a time, advancing a
       checkpoint after each block so a long (paid) run is resumable.

    Pipeline:
        output_data/scrapers/abstracts.csv  ->  THIS SCRIPT
            ->  output_data/classifiers/abstracts-classified.csv
            ->  output_data/classifiers/test-set-classified.csv (--test runs)

Checkpointing & resumability:
    Progress is tracked by CHECKPOINT in the repo-root .env: an integer row offset
    into the (test-filtered) dataframe. After each INTERVAL-row block is written,
    CHECKPOINT advances and is saved back to .env, so a crash or interrupt resumes
    from the last completed block instead of paying to re-classify rows.

Footguns (read before re-running):
    - Resuming vs. fresh start: output is appended whenever the output FILE exists
      (this keys off file existence, NOT CHECKPOINT). Resuming a run (CHECKPOINT > 0)
      correctly appends to the partial file it left behind. But starting fresh
      (CHECKPOINT reset to 0) WITHOUT deleting the old output appends the new run
      onto the old rows, so the file looks like every abstract was processed twice.
      Nothing was re-classified — the file just holds [old run] + [new run]. So when
      you zero CHECKPOINT, delete the output file first. (This append-on-existing
      behaviour is intentional: it also lets you classify a new conference's
      abstracts and append them onto an existing classified file.)
    - CHECKPOINT indexes by POSITION into the test-filtered dataframe, so resumption
      is only correct if every run filters to the exact same rows. The test set is
      stable, so this matches the old behaviour of reading a pre-filtered CSV — but
      if the test set changes mid-run, reset CHECKPOINT to 0 (and delete the output)
      to avoid skipping or reprocessing the wrong rows.

Requirements:
    - a repo-root .env with OPENAI_API_KEY and CHECKPOINT (start it at 0) set.
    - a prompt set JSON (default classifiers/prompts/prompts_safety.json) with a
      'classify' entry (the safety pass) plus one entry per category.

COMMENT: A better implementation would parallelize the classifier by using the OpenAI
Batch API, or fanning requests across async workers. I didn't have time to do this but
it would likely cut down on classification time tremendouse (right now its about ~48 hrs
per run based on our sample size of 55k rows).

Usage:
    python abstract_classifier.py                       # abstracts.csv -> abstracts-classified.csv
    python abstract_classifier.py -i in.csv -o out.csv  # custom input/output paths
    python abstract_classifier.py -p prompts.json       # custom prompt set
    python abstract_classifier.py --skip-classify       # reuse existing safety column, run category pass only
    python abstract_classifier.py --test                # classify the held-out test set instead of stripping it
"""

import pandas as pd
import json
import sys
import os
import argparse
from dotenv import load_dotenv, set_key
from openai import OpenAI
import tiktoken

# constants
LLM = 'gpt-5.2'
ENCODING_TYPE = 'gpt-5'
INTERVAL = 100 # interval at which we want the LLM to save its work
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)
ENV_PATH   = os.path.join(REPO_ROOT, ".env")  # repo-root .env

# importing remove_test_abstracts function from utils
sys.path.insert(0, os.path.join(REPO_ROOT, "utils"))
from remove_test_abstracts import remove_test_abstracts

# pipeline defaults: read the raw scraped abstracts, write the classified abstracts.
# The test set is stripped in-memory (see remove_test_abstracts) right after load, so
# there's no separate abstracts-filtered.csv intermediate to manage.
DEFAULT_INPUT  = os.path.join(REPO_ROOT, "output_data", "scrapers", "abstracts.csv")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "output_data", "classifiers", "abstracts-classified.csv")
# --test mode: classify the held-out test set itself (instead of stripping it out).
# Same two-pass classification as a normal run; just a different default input.
TEST_INPUT  = os.path.join(REPO_ROOT, "input_data", "test_data", "test_set.csv")
TEST_OUTPUT = os.path.join(REPO_ROOT, "output_data", "classifiers", "test-set-classified.csv")
# prompts are program config, kept alongside the classifier (not in input_data/)
DEFAULT_PROMPTS = os.path.join(SCRIPT_DIR, "prompts", "prompts_safety.json")

def classify_abstracts(client: OpenAI, df: pd.DataFrame, prompt: str, count: int, col_name: str):
    """
    classify abstracts using an LLM. returns a df and token count
    
    Args:
        client: OpenAI client instance
        df: Input DataFrame with abstracts
        prompt: Classification prompt to use
        count: Running token count from previous calls
        col_name: Name of column to store classification results
    """
    # prep for token count
    encoding = tiktoken.encoding_for_model(ENCODING_TYPE)
    total_tokens = count
    prompt_tokens = len(encoding.encode(prompt))
    
    # strip unnecessary columns to save on tokens 
    df_clean = df.drop(columns=['conference','url','uid'], errors='ignore')
    
    # classify each row
    for idx in df.index:
        input_data = json.dumps(df_clean.loc[idx].to_dict())
        tokens = len(encoding.encode(input_data))
        total_tokens += tokens + prompt_tokens
        
        result = client.responses.create(
            model = LLM,
            instructions = prompt,
            input = input_data,
            temperature = 0 # set temp to 0 for predictability
        )
        
        df.at[idx, col_name] = result.output_text # add result back to df
    return df, total_tokens

def load_chkpt(df: pd.DataFrame, chkpt: int, interval: int):
    """
    loads a subset of data from a checkpoint. returns a df
    
    Args:

    """
    # check if there are enough unprocessed rows to need checkpointing
    if len(df[chkpt:]) >= interval:
        df = df[chkpt:chkpt+interval].copy()
    else:
        df = df[chkpt:].copy() # else, just return what's left
    return df

def main():
    # load environment file
    load_dotenv(ENV_PATH)

    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', default=None, dest='input_csv',
                        help='Raw abstracts CSV to classify (default: output_data/scrapers/abstracts.csv)')
    parser.add_argument('-o', '--output', default=None, dest='output_csv',
                        help='Classified output CSV (default: output_data/classifiers/abstracts-classified.csv)')
    parser.add_argument('-p', '--prompts', default=DEFAULT_PROMPTS, dest='prompts_json',
                        help='Prompt set JSON (default: classifiers/prompts/prompts_safety.json)')
    parser.add_argument('--skip-classify', action='store_true',
                        help='Skip first-pass safety classification and use existing safety column values')
    parser.add_argument('--test', action='store_true',
                        help='Classify the held-out test set itself: skips remove_test_abstracts and '
                             'defaults input/output to input_data/test_data/test_set.csv and '
                             'output_data/classifiers/test-set-classified.csv (override with -i/-o)')
    args = parser.parse_args()

    # resolve input/output defaults (test mode points at the test set by default)
    input_csv  = args.input_csv  or (TEST_INPUT  if args.test else DEFAULT_INPUT)
    output_csv = args.output_csv or (TEST_OUTPUT if args.test else DEFAULT_OUTPUT)

    # reads input csv as a df
    df_full = pd.read_csv(input_csv)

    # In a normal run, strip the held-out test set in-memory so it never gets classified.
    # In --test mode we WANT the test set, so skip the filter entirely.
    # (See module docstring "Footguns" re: CHECKPOINT indexing into this filtered df.)
    if not args.test:
        df_full = remove_test_abstracts(df_full, TEST_INPUT)

    # read in prompts as a dict
    with open(args.prompts_json, 'r') as f:
        prompts = json.load(f)

    classify_prompt = prompts.pop('classify') # pop out classifier prompt

    # initialize all category columns in df_full to ensure consistent output structure
    all_prompt_categories = list(prompts.values()) + [classify_prompt]
    for category in all_prompt_categories:
        col = category['col_name']
        if col not in df_full.columns:
            df_full[col] = pd.NA
        df_full[col] = df_full[col].astype(object)  # prevent float64 inference which rejects string LLM outputs

    # initialize OpenAI client
    client = OpenAI()

    # get checkpoint from environment
    CHECKPOINT = int(os.getenv('CHECKPOINT'))

    # set token count
    count = 0

    # make sure the output directory exists before the write loop appends to it
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)

    while CHECKPOINT < len(df_full):
        try:
            # returns a subset df based on our last checkpoint
            df = load_chkpt(df_full, CHECKPOINT, INTERVAL)

            safety_col = classify_prompt['col_name']
            if args.skip_classify:
                # use pre-existing safety column values to filter
                df_safety = df[df[safety_col].astype(str).str.upper() == 'TRUE'].copy()
            else:
                # first pass classification of safety/no safety
                df, count = classify_abstracts(client, df, classify_prompt['prompt'], count, safety_col)
                df_safety = df[df[safety_col].astype(str).str.upper() == 'TRUE'].copy()

            # print progress at each checkpoint for debugging and runtime estimation
            print(f'Checkpoint {CHECKPOINT}: {len(df_safety)} safety rows found out of {len(df)}')

            # second pass for categorisation - looping through the list of all categories provided
            # in the prompts dict and performing one-hot encoding
            for category in prompts.values():
                cat_prompt = category['prompt']
                col_name = category['col_name']
                df_safety, count = classify_abstracts(client, df_safety, cat_prompt, count, col_name)

            # drop safety papers from original df and bind the newly categorised safety papers back
            df.loc[df_safety.index] = df_safety

            # append if the output file exists, else create it. This keys off file
            # existence so a resumed run appends to its partial file — but it also means a fresh run 
            # won't overwrite a stale file.
            # See module docstring "Footguns" before re-running.
            if os.path.exists(output_csv):
                df.to_csv(output_csv, mode='a', header=False, index=False, na_rep='NA')
            else:
                df.to_csv(output_csv, index=False, na_rep='NA')

            # update checkpoint in .env file
            CHECKPOINT = CHECKPOINT + INTERVAL
            set_key(ENV_PATH, 'CHECKPOINT', str(CHECKPOINT))

        except KeyboardInterrupt: # logic for user interrupt
            print(f'\n\nProcess interrupted by user at checkpoint {CHECKPOINT}')
            print(f'Tokens used so far: {count}')
            sys.exit(0)

        except Exception as e: # logic for errors
            print(f'\n\nError occurred at checkpoint {CHECKPOINT}: {str(e)}')
            print(f'Tokens used so far: {count}')
            sys.exit(1)

    print(f'\nTotal tokens used for {LLM}: {count}')

if __name__ == "__main__":
    main()