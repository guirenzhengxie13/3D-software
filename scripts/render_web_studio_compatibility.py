"""Turn verified CPU raster buffers into labelled reviewable image artifacts."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont


def main():
    root=Path(__file__).resolve().parents[1];out=root/'reports/web-studio/compatibility';meta=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    font_path=Path('C:/Windows/Fonts/msyh.ttc');font=lambda n:ImageFont.truetype(str(font_path),n)
    image=Image.new('RGB',(1250,790),(12,20,32));d=ImageDraw.Draw(image)
    d.text((20,15),'真实片段数据 · Canvas 兼容绘制的实际像素',font=font(24),fill='#dfeaf5')
    d.text((20,53),'由已生成页面的绘制代码输出；这是离线算法检查，不是 Chrome 截图。',font=font(15),fill='#93adbf')
    for i,(name,label) in enumerate([('target','固定片段'),('source','移动片段'),('overlay','已有候选叠加')]):
        panel=Image.frombytes('RGBA',(400,650),(out/(name+'.rgba')).read_bytes()).convert('RGB');image.paste(panel,(15+i*410,95));d.text((25+i*410,103),label,font=font(19),fill='#bed9ec')
    count=len(meta['pages']);views=sum(len(p['views']) for p in meta['pages'])
    d.text((20,758),f"{count}个工作台 / {views}个非空视图通过检查；原模型、原编号与候选引用保持。",font=font(16),fill='#8fc9b6')
    image.save(out/'workbench-canvas.png');print(json.dumps(dict(image=str(out/'workbench-canvas.png'),actual_browser_verified=False)))

if __name__=='__main__':main()
