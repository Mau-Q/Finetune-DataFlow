import json
import os
import hashlib
import pandas
import datetime
from typing import Dict, List, Optional, Any, Tuple
from app.services.task_store import patch_task, fail_submission
from app.services.resource_store import ResourceStore
from app.core.container import container
from app.core.config import settings
from app.services.dataflow_engine import DataFlowEngine
from app.core.logger_setup import get_logger

logger = get_logger(__name__)

class TaskRegistry:
    """任务注册表，用于管理运行任务的生命周期"""
    
    def __init__(self, path: str | None = None):
        self.path = path or settings.TASK_REGISTRY
        self._ensure()
    
    def _ensure(self):
        # 只在文件不存在时初始化
        if not os.path.exists(self.path):
            with ResourceStore(self.path).writing() as data:
                data.setdefault('tasks', {})
            return

        data = ResourceStore(self.path).read()
        if not isinstance(data.get('tasks'), dict):
            raise ValueError('任务注册表损坏，原文件已保留')


    def _read(self) -> Dict:
        """读取注册表"""
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f) or {"tasks": {}}

    def _write(self, data: Dict):
        """写入注册表"""
        with ResourceStore(self.path).writing() as current:
            current.clear()
            current.update(data)

    def _generate_task_id(self) -> str:
        """生成唯一的任务ID"""
        timestamp = pandas.Timestamp.now().isoformat()
        random_str = os.urandom(8).hex()
        combined = f"{timestamp}-{random_str}"
        return hashlib.md5(combined.encode("utf-8")).hexdigest()[:12]
    
    def list(self, status: Optional[str] = None, executor_type: Optional[str] = None) -> List[Dict]:
        """
        列出所有任务，可选过滤条件
        
        Args:
            status: 过滤特定状态的任务
            executor_type: 过滤特定类型的执行器 (operator/pipeline)
        """
        tasks = list(self._read()["tasks"].values())
        
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        
        if executor_type:
            tasks = [t for t in tasks if t.get("executor_type") == executor_type]
        
        # 按创建时间倒序排列
        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return tasks
    
    def create(self, task: Dict) -> Dict:
        """
        创建新任务
        
        Args:
            task: 任务信息字典
        
        Returns:
            创建的任务（包含生成的ID和时间戳）
        """
        # 生成任务ID
        task_id = self._generate_task_id()
        task["id"] = task_id
        task["status"] = "pending"  # 初始状态
        task["created_at"] = pandas.Timestamp.now().isoformat()
        task["started_at"] = None
        task["finished_at"] = None
        task["output_id"] = None
        task["error_message"] = None
        
        # 保存任务
        patch_task(self.path, task_id, task, create=True)
        
        return task
    
    def get(self, task_id: str) -> Dict | None:
        """获取指定任务"""
        return self._read()["tasks"].get(task_id)
    
    def update(self, task_id: str, updates: Dict) -> Dict | None:
        """
        更新任务信息
        
        Args:
            task_id: 任务ID
            updates: 要更新的字段
        
        Returns:
            更新后的任务，如果任务不存在返回None
        """
        updates = {key: value for key, value in updates.items() if value is not None}
        if updates.get('status') == 'running':
            updates.setdefault('started_at', pandas.Timestamp.now().isoformat())
        elif updates.get('status') in {'success', 'completed', 'failed', 'cancelled'}:
            updates.setdefault('finished_at', pandas.Timestamp.now().isoformat())
        return patch_task(self.path, task_id, updates)

    def delete(self, task_id: str) -> bool:
        """
        删除任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            是否成功删除
        """
        with ResourceStore(self.path).writing() as data:
            return data.setdefault('tasks', {}).pop(task_id, None) is not None

    def get_statistics(self) -> Dict:
        """
        获取任务统计信息
        
        Returns:
            统计信息字典
        """
        tasks = self.list()
        
        stats = {
            "total": len(tasks),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "queued": 0,
            "success": 0,
            "failed": 0,
            "cancelled": 0,
            "by_executor_type": {
                "operator": 0,
                "unknown": 0,
                "pipeline": 0
            }
        }
        
        for task in tasks:
            status = task.get("status", "queued")
            status = {"success": "completed", "pending": "queued"}.get(status, status)
            stats[status] = stats.get(status, 0) + 1
            
            executor_type = task.get("executor_type") or ("pipeline" if task.get("pipeline_id") else "operator" if task.get("executor_name") else "")
            if executor_type in stats["by_executor_type"]:
                stats["by_executor_type"][executor_type] += 1
            else:
                stats["by_executor_type"]["unknown"] += 1
        
        stats["success"] = stats.get("completed", 0)
        stats["pending"] = stats.get("queued", 0)
        return stats

    def get_current_time(self):
        """获取当前时间的ISO格式字符串"""
        return datetime.datetime.now().isoformat()

    def start_execution(self, pipeline_id: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """开始执行Pipeline"""
        # 获取Pipeline配置
        if pipeline_id:
            pipeline = container.pipeline_registry.get_pipeline(pipeline_id)
            if not pipeline:
                raise ValueError(f"Pipeline with id {pipeline_id} not found")
            pipeline_config = pipeline.get("config", {})
            logger.info(f"Executing predefined pipeline: {pipeline_id}")
        else:
            if not config:
                raise ValueError("Either pipeline_id or config must be provided")
            pipeline_config = config
            logger.info("Executing pipeline with provided config")
        
        from app.services.resource_resolution import resolve_pipeline_resources
        import copy
        pipeline_source_config = copy.deepcopy(pipeline_config)
        pipeline_config, resource_snapshots = resolve_pipeline_resources(pipeline_config)
        from app.services.auto_collection import freeze_collection_target
        if container.data_library is not None:
            freeze_collection_target(pipeline_config, container.data_library)

        from app.services.source_progress import freeze_source
        input_identity = freeze_source(pipeline_config, container.dataset_registry, container.data_library)

        # 生成执行ID
        task_id = self._generate_task_id()
        
        from app.services.result_storage import prepare
        if pipeline_config.get('execution_options', {}).get('output_root'):
            prepare(pipeline_config, task_id, pipeline.get('name', 'Pipeline') if pipeline_id else pipeline_config.get('execution_options', {}).get('pipeline_name', 'Pipeline'))

        # 创建初始结果记录
        initial_result = {
            "task_id": task_id,
            "pipeline_id": pipeline_id,
            "pipeline_config": pipeline_config,
            "pipeline_source_config": pipeline_source_config,
            "resource_snapshots": resource_snapshots,
            "input_identity": input_identity,
            "status": "queued",
            "output": {},
            "logs": [f"[{self.get_current_time()}] Pipeline execution queued"]
        }
                
        # 直接保存到文件
        initial_result['created_at'] = self.get_current_time()
        patch_task(self.path, task_id, initial_result, create=True)
        
        return task_id, pipeline_config, initial_result
    
    def list_executions(self) -> List[Dict[str, Any]]:
        """列出所有任务执行记录"""
        data = self._read()
        # 直接返回字典列表，不需要转换为对象
        return list(data.get("tasks", {}).values())
    
    def get_execution_status(
        self, 
        task_id: str,
    ) -> Dict[str, Any]:
        """
        获取执行状态（包含算子粒度）
        
        Args:
            task_id: 执行 ID
        
        Returns:
            执行状态字典
        """
        # 读取执行记录
        data = self._read()
        execution_data = data.get("tasks", {}).get(task_id)
        
        if not execution_data:
            return None
        
        # operator_progress is now deprecated, use operators_detail from output
        output = execution_data.get("output", {})
        
        return {
            "task_id": task_id,
            "pipeline_id": execution_data.get("pipeline_id"),
            "pipeline_config": execution_data.get("pipeline_config"),
            "pipeline_source_config": execution_data.get("pipeline_source_config"),
            "resource_snapshots": execution_data.get("resource_snapshots", []),
            "status": execution_data.get("status"),
            "operators_detail": output.get("operators_detail", {}),
            "operator_logs": output.get("operator_logs", {}),
            "logs": execution_data.get("logs", []),
            "auto_collection": output.get("auto_collection"),
            # "output": output, # Output removed as requested to avoid duplication
            "started_at": execution_data.get("started_at"),
            "completed_at": execution_data.get("completed_at"),
        }
    
    def get_execution_logs(self, task_id: str, operator_name: Optional[str] = None) -> List[str]:
        """获取任务日志，可选过滤指定算子"""
        data = self._read()
        execution_data = data.get("tasks", {}).get(task_id)
        if not execution_data:
            return []
        
        # 如果是查询全局日志/流水线日志
        if not operator_name:
            return execution_data.get("logs", [])
        
        # Assuming we only care about completed logs or what's available.
        output = execution_data.get("output", {})
        operator_logs = output.get("operator_logs", {})
        
        # Try to find by operator name
        target_logs = []
        
        # First check structured logs
        if operator_name in operator_logs:
            return operator_logs[operator_name]
            
        # If not indexed by simple name, maybe key is op_key
        # Try finding key ending with name or just name
        for k, v in operator_logs.items():
            if k == operator_name or k.startswith(f"{operator_name}_"):
                return v

        # Default fallback to searching in main logs?
        return []

    def get_execution_result(
        self, 
        task_id: str,
        step: Optional[int] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        获取执行结果
        
        Args:
            task_id: 执行 ID
            step: 步骤索引（可选，None 表示返回最后一个步骤的输出）
            limit: 返回的数据条数（默认5条）
        
        Returns:
            执行结果字典
        """
        data = self._read()
        execution_data = data.get("tasks", {}).get(task_id)
        
        if not execution_data:
            return None
        
        # 获取输出
        output = execution_data.get("output", {})
        logs = execution_data.get("logs", [])
        
        # 获取执行结果和算子进度
        execution_results = output.get("execution_results", [])
        operators_detail = output.get("operators_detail", {})
        operator_logs = output.get("operator_logs", {})
        
        # 确定要查询的步骤索引
        if step is None:
            # 默认返回最后一个已完成的步骤
            if execution_results:
                step = execution_results[-1].get("index", 0)
            else:
                # 尝试查找正在运行的步骤
                # Find operator with status 'running' in operators_detail
                running_op = None
                for op_key, op_info in operators_detail.items():
                    if op_info.get("status") == "running":
                        running_op = op_info
                        break
                
                if running_op:
                    step = running_op.get("index", 0)
                else:
                    step = 0
        
        # 读取缓存文件（使用绝对路径）
        cache_path = os.path.join(settings.CACHE_DIR, f"{task_id}_output")
        cache_file = os.path.join(cache_path, f"dataflow_cache_step_step{step+1}.jsonl")
        sample_data = []
        total_count = 0
        file_exists = False

        if os.path.exists(cache_file):
            file_exists = True
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    for line in f:
                        total_count += 1
                        if len(sample_data) < limit:
                            try:
                                sample_data.append(json.loads(line.strip()))
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                logger.error(f"Failed to read cache file {cache_file}: {e}")
        
        # 获取算子信息
        operator_name = None
        operator_status = None
        
        # 从 operators_detail 中查找
        # Need to find entry with index == step
        for op_key, op_val in operators_detail.items():
            if op_val.get("index") == step:
                operator_name = op_val.get("name")
                operator_status = op_val.get("status")
                break

        return {
            "task_id": task_id,
            "pipeline_id": execution_data.get("pipeline_id"),
            "pipeline_config": execution_data.get("pipeline_config"),
            "pipeline_source_config": execution_data.get("pipeline_source_config"),
            "resource_snapshots": execution_data.get("resource_snapshots", []),
            "status": execution_data.get("status"),
            "step": step,
            "operator_name": operator_name,
            "operator_status": operator_status,
            "sample_data": sample_data,
            "sample_count": len(sample_data),
            "total_count": total_count,
            "file_exists": file_exists,
            "cache_file": cache_file,
            "logs": logs,
            "operator_logs": operator_logs,
            "started_at": execution_data.get("started_at"),
            "completed_at": execution_data.get("completed_at"),
            "operators_detail": operators_detail 
        }
    
    async def start_execution_async(
        self, 
        pipeline_id: Optional[str] = None, 
        config: Optional[Dict[str, Any]] = None, output_root: Optional[str] = None,
        collection_target: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        异步开始执行Pipeline（使用 Ray）
        
        Args:
            pipeline_id: 预定义 Pipeline ID
            config: 自定义 Pipeline 配置
        
        Returns:
            包含 task_id 的字典
        """
        from app.services.ray_pipeline_executor import ray_executor
        
        # 获取Pipeline配置
        if pipeline_id:
            pipeline = container.pipeline_registry.get_pipeline(pipeline_id)
            if not pipeline:
                raise ValueError(f"Pipeline with id {pipeline_id} not found")
            pipeline_config = pipeline.get("config", {})
            logger.info(f"Executing predefined pipeline asynchronously: {pipeline_id}")
        else:
            if not config:
                raise ValueError("Either pipeline_id or config must be provided")
            pipeline_config = config
            logger.info("Executing pipeline with provided config asynchronously")
        
        import copy
        pipeline_config = copy.deepcopy(pipeline_config)
        if collection_target is not None:
            pipeline_config.setdefault('execution_options', {})['collection_target'] = collection_target
        if output_root is not None:
            options = pipeline_config.setdefault('execution_options', {})
            options['output_root'] = output_root
            if pipeline_id:
                options['pipeline_name'] = pipeline.get('name', 'Pipeline')
        task_id, pipeline_config, initial_result = self.start_execution(config=pipeline_config)
        try:
            if pipeline_id:
                patch_task(self.path, task_id, {'pipeline_id': pipeline_id, 'name': pipeline.get('name', 'Pipeline')})
            dataflow_runtime = DataFlowEngine.decode_hashed_arguments(pipeline_config, task_id)

            # 提交到 Ray 异步执行
            await ray_executor.submit_execution(
                pipeline_config=pipeline_config,
                dataflow_runtime=dataflow_runtime,
                task_id=task_id,
                pipeline_registry_path=self.path,
                pipeline_execution_path=self.path
            )

        except BaseException as exc:
            fail_submission(self.path, task_id, exc)
            raise

        logger.info(f"Pipeline execution submitted to Ray: {task_id}")
        
        return {
            "task_id": task_id
        }

    def kill_execution(self, task_id: str) -> bool:
        """
        终止指定的 Pipeline 执行任务
        
        Args:
            task_id: 执行 ID
        
        Returns:
            是否成功终止
        """
        from app.services.ray_pipeline_executor import ray_executor
        from datetime import datetime
        
        # 1. 直接读取最新数据
        data = self._read()
        task_record = data.get("tasks", {}).get(task_id)
        
        if not task_record:
            logger.warning(f"Task {task_id} not found")
            return False
        
        # 检查任务状态
        status = task_record.get("status", "pending")
        if status in ["success", "completed", "failed", "cancelled"]:
            logger.warning(f"Task {task_id} is already {status}, cannot kill")
            return False
        
        try:
            # 2. 物理 Kill
            # 注意：先 Kill 进程，后改状态。
            # 这样即使 Kill 之后 worker 还有最后一丝余力想写文件，也会因为进程被切断而停止
            killed_via_ray = ray_executor.kill_execution(task_id)
            
            # 3. 构造状态更新
            now = datetime.now().isoformat()
            task_record["status"] = "cancelled"
            task_record["finished_at"] = now
            task_record["error_message"] = "Task was killed by user"
            
            # ✅ 关键：同步更新内部算子的状态，让 UI 显示更准确
            if "output" in task_record and "operators_detail" in task_record["output"]:
                for op_key, op_info in task_record["output"]["operators_detail"].items():
                    if op_info.get("status") in ["running", "initializing"]:
                        op_info["status"] = "cancelled"
                        op_info["completed_at"] = now
            
            # 4. 强制写回磁盘（覆盖式更新）
            patch_task(self.path, task_id, task_record)
            
            logger.info(f"Task {task_id} killed. Ray_success: {killed_via_ray}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to kill task {task_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 即使发生异常，也尝试更新任务状态
            try:
                now = datetime.now().isoformat()
                task_record["status"] = "cancelled"
                task_record["finished_at"] = now
                task_record["error_message"] = f"Task kill failed: {str(e)}"
                
                # 同步更新内部算子的状态
                if "output" in task_record and "operators_detail" in task_record["output"]:
                    for op_key, op_info in task_record["output"]["operators_detail"].items():
                        if op_info.get("status") in ["running", "initializing"]:
                            op_info["status"] = "cancelled"
                            op_info["completed_at"] = now
                
                patch_task(self.path, task_id, task_record)
                logger.info(f"Task {task_id} status updated to cancelled despite error")
                return True
            except Exception as update_error:
                logger.error(f"Failed to update task {task_id} status after kill failure: {update_error}")
                return False
