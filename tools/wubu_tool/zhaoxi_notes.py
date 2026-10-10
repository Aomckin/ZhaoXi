"""给朝汐的调用注释：导出到工具 description，随工具定义提供给模型。"""
ZHAOXI_NOTES = (
    "【给朝汐的调用注释】购买和费用记账使用物簿，LifeHUD生活记录不能代替账目。"
    "优先对应独立工具，按schema提交合法JSON；独立工具不套operation/payload，只有高级wubu使用这两层。"
    "首次购买直接record_purchase，无需先查或创建商品；2L是spec，买一瓶是quantity=1、unit=瓶。"
    "使用用户明确的信息，不编造金额、规格或账户。只有成功写入才能说已完成；查询和预检查不等于记账。"
    "Connection refused时tool会按配置自动启动物簿并等待就绪，无需朝汐另行启动或重复调用。"
    "其他错误按code/message/suggested_action处理；超时或unknown_outcome=true时说明结果未知，"
    "不得换幂等键重发，不把未执行动作说成已完成。"
)
