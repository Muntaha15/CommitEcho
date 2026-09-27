import sys, json
sys.path.insert(0, 'src')
from pathlib import Path
from commitecho.git.adapter import GitAdapter
from commitecho.storage.db import open_drafts_db, open_index_db
from commitecho.application.retrieve import RetrieveService

repo = Path('tests/fixtures/repos/chosen_and_rejected')
git = GitAdapter.from_path(repo)
drafts = open_drafts_db(git.repo_info.common_dir)
index = open_index_db(git.repo_info.common_dir)

# Check FTS state
try:
    fts = index.execute('SELECT * FROM decisions_fts').fetchall()
    print('FTS rows:', len(fts))
    for r in fts:
        print(' FTS row:', dict(r))
except Exception as e:
    print('FTS error:', e)

# Check indexed_records
recs = index.execute('SELECT record_id, commit_oid FROM indexed_records').fetchall()
print('indexed_records:', len(recs))

retrieve = RetrieveService(drafts, index, git)
resp = retrieve.search_history(question='duplicate uploads on retry', page_size=5)
print('results:', len(resp['results']))
print('coverage_notes:', resp['coverage_notes'])
