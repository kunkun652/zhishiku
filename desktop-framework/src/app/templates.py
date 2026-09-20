"""Versioned engineering object templates; values are deliberately empty."""
COMMON = [('summary','用途说明'),('source','来源文件 / 页码 / 表号'),('category','资料分类'),('rights','使用 / 训练权限'),('scope','适用范围'),('analysis_type','分析类型'),('units','单位制'),('limitations','限制与禁用条件'),('verification','验证依据'),('original_record','原始结构化记录（保留字段）')]
DEFS = {
 'material': ('材料卡','材料本体；数值、单位和字段来源分开记录，不包含厚度与铺层。', [('designation','材料牌号'),('state','材料状态'),('temperature','适用温度'),('direction','方向'),('solver_card','MAT1 / MAT8'),('properties','参数列表（JSON）')]),
 'term': ('术语卡','定义、同义词与易混淆边界；帮助中文和英文检索。',[('definition','定义'),('aliases','别名 / 英文名'),('dimension','量纲'),('confusions','易混淆概念')]),
 'mesh': ('网格策略卡','几何特征、网格方法、质量规则与收敛依据。',[('geometry','适用几何'),('element_type','单元类型'),('method','划分方法'),('quality','质量指标及来源'),('convergence','收敛要求')]),
 'condition': ('工况卡','区分 core / conditional / upstream / mesh / material；载荷必须绑定当前模型。',[('level','适用层级'),('core','核心条件 core'),('conditional','条件依赖 conditional'),('upstream','上游载荷 upstream'),('mesh','网格依赖 mesh'),('material','材料依赖 material'),('loads','载荷与来源'),('constraints','约束与作用区域')]),
 'document': ('资料与依据','原件按内容哈希去重；正文按页定位，扫描缺口单独登记。',[('author','作者 / 发布机构'),('revision','原文版本'),('locator','页码 / 章节'),('license','使用权限'),('extraction_status','正文提取状态')]),
 'model': ('模型资产','CAD / 网格 / 输入 / 结果独立登记；模型变化后重新核查区域映射。',[('format','文件格式'),('coordinate_system','坐标系'),('geometry_version','几何版本'),('mesh_version','网格版本'),('regions','语义区域映射（JSON）'),('preview_variable','结果变量 / 分量 / 步'),('property_binding','厚度 / 截面 / 铺层依据')]),
 'case': ('仿真案例','积累完整过程和差异，成功运行不等于工程验收。',[('goal','任务目标'),('assumptions','假设'),('model_ids','模型引用'),('card_ids','卡片引用'),('steps','步骤与工具版本'),('differences','可复用内容与差异'),('inputs','求解输入 BDF 等'),('logs','求解日志 F06 等'),('results','结果 OP2 等'),('visual_evidence','结果显示证据'),('checks','独立检查'),('failure','失败原因与恢复')]),
 'workflow': ('流程规则','步骤依赖、输入输出、分支和停止条件。',[('goal','目标'),('steps','有序步骤与依赖'),('inputs','输入'),('outputs','输出'),('branches','分支规则'),('stop','停止条件')]),
 'skill': ('Skill 方法','只登记方法和契约，执行环境由智能体管理。',[('goal','能力目标'),('preconditions','前置条件'),('inputs','输入格式'),('outputs','输出与完成条件'),('tools','工具与版本依赖'),('parameters','参数获取规则'),('checks','检查项'),('recovery','恢复与重试上限'),('stop','停止条件'),('cases','验证案例')]),
 'tool': ('Tool 能力','登记真实工具契约；本产品不启动仿真工具。',[('interface','接口名称'),('version','工具版本'),('input_schema','输入结构'),('output_schema','返回结构'),('formats','支持格式'),('environment','运行环境'),('availability','可用性及实测证据')]),
 'validation': ('验证基准','检查规则、阈值和容差必须有依据。',[('method','检查方法'),('expected','预期结果'),('tolerance','容差与来源'),('benchmark','基准资产'),('procedure','检查程序')]),
 'failure': ('失败经验','记录证据、修复尝试与停止条件，先作为候选。',[('symptom','错误现象 / 代码'),('evidence','诊断证据'),('cause','原因'),('recovery','适用修复'),('failed_attempts','失败尝试'),('stop','停止条件')]),
 'task': ('任务定义','先定义任务与缺口，再锁定知识版本。',[('goal','分析目标'),('model_ids','模型与版本'),('loads','载荷依据'),('constraints','边界条件'),('resources','软件与资源'),('deliverables','交付物'),('acceptance','验收要求')]),
 'run': ('运行记录','工具成功、自动检查、人员复核分开保存。',[('task_id','任务 ID'),('step','当前步骤'),('tool_calls','工具调用与真实返回'),('artifacts','输入 / 日志 / 结果 / 截图'),('tool_status','工具运行状态'),('automatic_checks','自动检查结果'),('human_review','人工复核记录'),('decision','选用理由'),('failure','失败与恢复')]),
 'gap': ('知识与能力缺口','区分资料缺失、条件不明和检索故障。',[('task_id','关联任务'),('stage','受阻步骤'),('category','缺口类别'),('missing','缺少什么'),('searched','已检索范围'),('resolution','补齐后验收方式')]),
 'dataset': ('训练 / 评测登记','只登记经筛选样本；按来源和模型家族隔离。',[('family','模型家族 / 案例来源'),('split','训练 / 评测划分'),('run_ids','运行记录引用'),('selection','筛选与纠错依据'),('review','复核记录')])
}
JSON_FIELDS = {'properties','regions'}
TEMPLATES = {key:{'type':key,'label':label,'description':desc,'schema_version':1,'fields':[{'key':k,'label':v,'kind':'json' if k in JSON_FIELDS else 'text'} for k,v in COMMON+fields]} for key,(label,desc,fields) in DEFS.items()}
RELATIONS = ['来源于','使用模型','采用材料','采用工况','采用网格策略','载荷来自','参考案例','执行流程','包含步骤','由Skill实现','调用工具','验收依据','产生结果','运行记录','存在缺口','区域映射','版本替代']
