# Registry Container

class AppContainer:
    """
    这里主要是为了解决之前直接在module里面全局初始化对象时，各个Registry被实例化的顺序不可控的问题。
    """
    def __init__(self):
        self.dataset_registry = None
        self.operator_registry = None
        self.prompt_registry = None
        self.serving_registry = None
        self.task_registry = None
        self.pipeline_registry = None
        self.text2sql_database_registry = None
        self.text2sql_database_manager_registry = None
        self.dataset_visualize_service = None
        self.json_schema_manager = None
        self.user_prompt_registry = None
        self.data_library = None
        self.model_training = None

    def init(self):
        from app.services.dataset_registry import DatasetRegistry, VisualizeDatasetService
        from app.services.pipeline_registry import PipelineRegistry
        from app.services.operator_registry import OperatorRegistry
        from app.services.prompt_registry import PromptRegistry
        from app.services.serving_registry import ServingRegistry
        from app.services.task_registry import TaskRegistry
        from app.services.text2sql_database_registry import Text2SQLDatabaseRegistry, Text2SQLDatabaseManagerRegistry
        from app.services.json_schema_manager import JsonSchemaManager
        from app.services.user_prompt_registry import UserPromptRegistry
        
        from .config import settings
        import importlib
        # 动态加载DataFlow扩展模块
        for ext in settings._DATAFLOW_EXTENSIONS:
            try:
                importlib.import_module(ext)
                print(f"Successfully loaded DataFlow extension: {ext}")
            except ImportError as e:
                print(f"Failed to load DataFlow extension '{ext}': {e}")
        # 检查是否在 Ray worker 中运行
        import ray
        is_ray_worker = ray.is_initialized() and ray.get_runtime_context().worker.mode != 0

        # 初始化顺序在这里完全由你控制
        self.dataset_registry = DatasetRegistry(scan=not is_ray_worker)
        self.dataset_visualize_service = VisualizeDatasetService()
        self.operator_registry = OperatorRegistry()
        self.prompt_registry = PromptRegistry()
        self.serving_registry = ServingRegistry()
        self.task_registry = TaskRegistry()
        self.pipeline_registry = PipelineRegistry()
        self.text2sql_database_registry = Text2SQLDatabaseRegistry()
        self.text2sql_database_manager_registry = Text2SQLDatabaseManagerRegistry()
        self.json_schema_manager = JsonSchemaManager()
        self.user_prompt_registry = UserPromptRegistry()
        from app.services.data_library import DataLibrary
        self.data_library = DataLibrary()
        import os
        if os.environ.get('DATAFLOW_TEAM_WORKER'):
            from app.services.data_exports import DataExports
            DataExports(self.data_library).recover_interrupted()
        from app.services.model_training import ModelTraining
        from pathlib import Path
        import os
        try:
            self.model_training = ModelTraining(os.environ.get('DATAFLOW_TRAINING_DIR') or Path(settings.BASE_DIR) / settings.RESOURCE_DIR / 'model_training', self.data_library)
        except ValueError as exc:
            self.model_training_error = str(exc)
        if not is_ray_worker:
            from app.services.representative_training import install_templates
            install_templates(self)



# 创建一个全局 container（模块级单例）
container = AppContainer()
