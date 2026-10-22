"""Keep empty JSONL schemas across filtering steps in training workflows."""
import json
from pathlib import Path
import pandas as pd
from dataflow.utils.storage import FileStorage
from app.services.dataset_persistence import atomic_write


class TrainingFileStorage(FileStorage):
    def read(self, output_type='dataframe'):
        frame = super().read('dataframe')
        schema = Path(self._get_cache_file_path(self.operator_step) + '.columns.json')
        if frame.empty and schema.is_file():
            frame = pd.DataFrame({column: pd.Series(dtype='object') for column in json.loads(schema.read_text('utf-8'))})
        return self._convert_output(frame, output_type)

    def write(self, data):
        columns = list(data.columns)
        if data.empty:
            # Some upstream operators lose their input columns on an empty mask.
            columns = list(dict.fromkeys([*self.read('dataframe').columns, *columns]))
            data = data.reindex(columns=columns)
        path = super().write(data)
        atomic_write(Path(path + '.columns.json'), json.dumps(columns).encode())
        return path
