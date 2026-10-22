"""Reproducible local fixtures. No model, network, or database operation."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
TEXTS = [
    ('sampling', '某实验室的数据采集器每隔两秒记录一次温度，记录频率在本次实验期间保持不变。实验从第一条记录开始连续采集五分钟，按每分钟六十秒计算，总记录数按采样频率乘以时长计算，不额外增加端点记录。每条记录占用八个字节，其中已经包含温度值和时间信息。存储量只统计记录本身，不计算文件头、索引和文件系统开销。所有温度记录都成功写入，实验期间没有丢包、重复记录或压缩。请严格使用这些条件讨论本次采集的记录数量和存储量。'),
    ('lru', '一个采用 LRU 策略的缓存最多容纳三个页面，开始时缓存为空。LRU 在缓存已满且发生缺页时淘汰最近最久没有被访问的页面。访问序列依次为页面一、页面二、页面三、页面一、页面四，页面编号仅表示不同页面。命中页面会把该页面更新为最近使用，但不会增加缓存容量。每次未命中的页面都会被装入，且每次装入仅占据一个页面位置。本例没有预取、后台淘汰或并发访问，缓存状态只由上述访问序列决定。分析缓存状态时，应区分访问次数、缺页次数与最终保留的页面集合。'),
    ('split', '一个分类数据集共有一千条互不重复的样本，研究者按八比一比一划分训练集、验证集和测试集。训练集用于更新模型参数，验证集用于选择超参数，测试集只用于最终报告。划分之前已经按用户分组，同一用户的全部样本只能出现在一个子集中，本例假定划分比例能够精确实现。任何需要根据数据估计参数的标准化操作都只在训练集上拟合，再应用于验证集和测试集。后续生成的新训练样本不得包含测试集原文或同一用户的信息。讨论各子集数量和用途时，必须保留这些防止信息泄漏的限制条件。'),
    ('metrics', '某二分类检测器在固定测试集上识别目标事件，真阳性共有十八次，假阳性共有六次，假阴性共有两次。准确率以外，本次重点报告精确率和召回率，且不使用四舍五入后的中间值。精确率定义为真阳性除以真阳性与假阳性之和，反映报告为阳性的结果中有多少确实是阳性。召回率定义为真阳性除以真阳性与假阴性之和，反映真实阳性中被检测出来的比例。本例的统计对象都是事件，且没有多标签、样本权重或重复计数。问题中若要求百分数，应将相应比例乘以一百并加上百分号。'),
    ('version', '一个训练数据集的第一版包含一百二十条样本，每条样本都有稳定的样本标识。质量复核发现其中十五条存在来源不明确的问题，发布第二版时将这十五条剔除。随后又加入三十条经过人工检查的新样本，这些新样本与保留的旧样本没有重复。第二版只由保留下来的旧样本和这批新样本组成，没有其他增加或删除。第一版已经发布，因此仍作为历史版本保存，第二版的改动不会反向修改第一版文件。版本说明需要记录删除原因、新增来源以及两个版本之间的样本数量变化。'),
    ('retry', '某本地数据流水线包含清洗、生成和评价三个阶段，每个阶段成功结束后都会保存独立产物。第一次运行时清洗和生成成功，评价阶段因网络超时失败，失败并不表示已生成的回答质量不合格。任务固定了原始输入的内容哈希与提示词快照，重跑时必须先核对这些固定内容。系统允许一次额外请求重试，因此单个请求最多尝试两次；额外重试次数与总尝试次数不是同一个数。若原始输入文件已经变化，旧任务不能直接按新内容继续，而需要创建新任务。仅当全部阶段成功且最终训练文件校验通过时，才允许把产物收录到训练数据集。'),
]


def font(size):
    candidates = ['/System/Library/Fonts/STHeiti Light.ttc', '/System/Library/Fonts/PingFang.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    path = next((p for p in candidates if Path(p).is_file()), None)
    if path is None:
        raise RuntimeError('需要本地中文字体；可修改 font() 指向已安装字体，不会自动下载')
    return ImageFont.truetype(path, size)


def canvas(title):
    im = Image.new('RGB', (1100,720), '#f7f9fc')
    draw = ImageDraw.Draw(im)
    draw.text((55,35), title, font=font(38), fill='#172b4d')
    draw.text((55,100),'本地合成验收材料 · 数值仅用于测试',font=font(22),fill='#607087')
    return im,draw


def table(title, headers, rows):
    im, draw = canvas(title)
    width = 960/len(headers)
    for r, values in enumerate([headers,*rows]):
        for c,value in enumerate(values):
            x,y = 60+c*width,180+r*95
            draw.rectangle((x,y,x+width,y+95),fill='#dce8fb' if r==0 else 'white',outline='#879bb6',width=2)
            draw.text((x+22,y+30),str(value),font=font(28),fill='#172b4d')
    return im


def bars(title, entries, unit):
    im, draw = canvas(title)
    top = max(v for _,v in entries)
    for i,(label,value) in enumerate(entries):
        x = 100+i*(900/len(entries))
        height = value/top*340
        draw.rectangle((x,560-height,x+120,560),fill=['#2864c9','#1b8a77','#b47520','#7b52aa'][i%4])
        draw.text((x,580),label,font=font(26),fill='#172b4d')
        draw.text((x,520-height),str(value),font=font(30),fill='#172b4d')
    draw.text((60,650),'单位：'+unit,font=font(24),fill='#172b4d')
    return im


def flow(title, labels, footer):
    im, draw = canvas(title)
    gap=1000/len(labels)
    for i,label in enumerate(labels):
        x=45+i*gap
        draw.rounded_rectangle((x,270,x+gap-30,390),radius=15,fill='#dce8fb',outline='#2864c9',width=3)
        draw.text((x+15,310),label,font=font(26),fill='#172b4d')
        if i < len(labels)-1:
            draw.line((x+gap-28,330,x+gap-5,330),fill='#2864c9',width=4)
            draw.polygon(((x+gap-5,330),(x+gap-14,322),(x+gap-14,338)),fill='#2864c9')
    draw.text((60,490),footer,font=font(26),fill='#172b4d')
    return im


def generate():
    images=ROOT/'images';images.mkdir(exist_ok=True)
    rows=[{'id':key,'text':text} for key,text in TEXTS]
    rows[0]['text']='\n  '+rows[0]['text'].replace('。','。   \n')+'  \n'
    rows += [{'id':'duplicate-sampling','text':rows[0]['text']}, {'id':'too-short','text':'材料太短，无法关联事实。'}, {'id':'blank','text':'   '}]
    (ROOT/'text.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),'utf-8')
    (ROOT/'text-one.jsonl').write_text(json.dumps(rows[0],ensure_ascii=False)+'\n','utf-8')
    fixtures = [
        ('01-lab-table.png',table('实验室周末使用记录',['实验室','使用时长（小时）'],[['A',8],['B',12],['C',6]]), 'A 8小时，B 12小时，C 6小时；B最长，比A多4小时，总计26小时。'),
        ('02-model-table.png',table('模拟模型评测结果',['模型','正确率（%）','延迟（毫秒）'],[['A',82,120],['B',88,180],['C',85,150]]), 'A 82%/120毫秒，B 88%/180毫秒，C 85%/150毫秒；B正确率最高，A延迟最低。'),
        ('03-cache-chart.png',bars('模拟存储访问延迟',[('L1',2),('L2',8),('内存',80)],'时钟周期'), 'L1 2周期，L2 8周期，内存80周期；L2是L1的4倍，内存是L2的10倍。'),
        ('04-yield-chart.png',bars('数据处理各阶段保留数量',[('原始',100),('清洗后',80),('生成后',60),('准入后',45)],'条'), '原始100、清洗后80、生成后60、准入后45；最终为原始45%，评价阶段减少15条。'),
        ('05-pipeline-flow.png',flow('数据生成处理顺序',['输入','清洗','生成','评价','导出'],'箭头表示执行先后；评价完成后才导出。'), '输入→清洗→生成→评价→导出；清洗在生成之前，评价在生成之后、导出之前。'),
        ('06-retry-flow.png',flow('失败请求的重试路径',['首次请求','首次失败','额外重试','记录结果'],'最多额外重试 1 次；重试仍失败则记录失败，不保存为成功。'), '首次失败后最多额外重试1次，总尝试最多2次；重试仍失败要记录失败，不能当作成功。'),
    ]
    truths=[]
    for filename,im,truth in fixtures:
        im.save(images/filename)
        truths.append({'file':filename,'facts':truth})
    # Manual reference is deliberately separate from pipeline input.
    (ROOT/'manual-reference.json').write_text(json.dumps({'images':truths,'text':[
        {'id':'sampling','facts':'150条记录，1200字节，排除端点额外记录与其他开销。'},
        {'id':'lru','facts':'4次缺页；访问页面四时淘汰页面二，最终保留页面三、一、四。'},
        {'id':'split','facts':'训练800、验证100、测试100；用户不能跨集合，标准化仅训练集拟合。'},
        {'id':'metrics','facts':'精确率18/24=75%，召回率18/20=90%。'},
        {'id':'version','facts':'第二版120-15+30=135条；历史第一版不变。'},
        {'id':'retry','facts':'一次额外重试，总尝试2次；输入变化需新任务；失败不能收录。'},
    ],'input_checks':{'text_rows':9,'unique_valid_texts':6,'duplicate_rows':1,'short_or_blank_rows':2}},ensure_ascii=False,indent=2),'utf-8')


if __name__=='__main__':
    generate()
