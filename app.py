import os
import numpy as np
import random
import torch
import torchvision.transforms as transforms
from PIL import Image
from models.tag2text import tag2text_caption
from util import *
import gradio as gr
from chatbot import *
from load_internvideo import *
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
from simplet5 import SimpleT5
from models.grit_model import DenseCaptioning
bot = ConversationBot()
image_size = 384
normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                std=[0.229, 0.224, 0.225])
transform = transforms.Compose([transforms.ToPILImage(),transforms.Resize((image_size, image_size)),transforms.ToTensor(),normalize])


# define model
model = tag2text_caption(pretrained="pretrained_models/tag2text_swin_14m.pth", image_size=image_size, vit='swin_b' )
model.eval()
model = model.to(device)
print("[INFO] initialize caption model success!")

model_T5 = SimpleT5()
if torch.cuda.is_available():
    model_T5.load_model(
        "t5", "./pretrained_models/flan-t5-large-finetuned-openai-summarize_from_feedback", use_gpu=True)
else:
    model_T5.load_model(
        "t5", "./pretrained_models/flan-t5-large-finetuned-openai-summarize_from_feedback", use_gpu=False)
print("[INFO] initialize summarize model success!")
# action recognition
intern_action = load_intern_action(device)
trans_action = transform_action()
topil =  T.ToPILImage()
print("[INFO] initialize InternVideo model success!")

dense_caption_model = DenseCaptioning(device)
dense_caption_model.initialize_model()
print("[INFO] initialize dense caption model success!")

def inference(video_path, input_tag, progress=gr.Progress()):
    data = loadvideo_decord_origin(video_path)
    progress(0.2, desc="Loading Videos")

    # InternVideo
    action_index = np.linspace(0, len(data)-1, 8).astype(int)
    tmp,tmpa = [],[]
    for i,img in enumerate(data):
        tmp.append(transform(img).to(device).unsqueeze(0))
        if i in action_index:
            tmpa.append(topil(img))
    action_tensor = trans_action(tmpa)
    TC, H, W = action_tensor.shape
    action_tensor = action_tensor.reshape(1, TC//3, 3, H, W).permute(0, 2, 1, 3, 4).to(device)
    prediction = intern_action(action_tensor)
    prediction = F.softmax(prediction, dim=1).flatten()
    prediction = kinetics_classnames[str(int(prediction.argmax()))]

    # dense caption
    dense_caption = []
    dense_index = np.arange(0, len(data)-1, 5)
    original_images = data[dense_index,:,:,::-1]
    for original_image in original_images:
        dense_caption.append(dense_caption_model.run_caption_tensor(original_image))
    dense_caption = ' '.join([f"Second {i+1} : {j}.\n" for i,j in zip(dense_index,dense_caption)])
    
    # Video Caption
    image = torch.cat(tmp).to(device)   
    
    model.threshold = 0.68
    if input_tag == '' or input_tag == 'none' or input_tag == 'None':
        input_tag_list = None
    else:
        input_tag_list = []
        input_tag_list.append(input_tag.replace(',',' | '))
    with torch.no_grad():
        caption, tag_predict = model.generate(image,tag_input = input_tag_list,max_length = 50, return_tag_predict = True)
        progress(0.6, desc="Watching Videos")
        frame_caption = ' '.join([f"Second {i+1}:{j}.\n" for i,j in enumerate(caption)])
        if input_tag_list == None:
            tag_1 = set(tag_predict)
            tag_2 = ['none']
        else:
            _, tag_1 = model.generate(image,tag_input = None, max_length = 50, return_tag_predict = True)
            tag_2 = set(tag_predict)
        progress(0.8, desc="Understanding Videos")
        synth_caption = model_T5.predict('. '.join(caption))
    print(frame_caption, dense_caption, synth_caption)
    return ' | '.join(tag_1),' | '.join(tag_2), frame_caption, dense_caption, synth_caption[0], gr.update(interactive = True), prediction



with gr.Blocks(css="#chatbot {overflow:auto; height:500px;}") as demo:
    gr.Markdown("<h1><center>Ask Anything with GPT</center></h1>")
    gr.Markdown(
        """
        Ask-Anything is a multifunctional video question answering tool that combines the functions of Action Recognition, Visual Captioning and ChatGPT. Our solution generates dense, descriptive captions for any object and action in a video, offering a range of language styles to suit different user preferences. It supports users to have conversations in different lengths, emotions, authenticity of language.<br>  
        """
    )
    
    with gr.Row():
        with gr.Column():
            input_video_path = gr.inputs.Video(label="Input Video")
            input_tag = gr.inputs.Textbox(lines=1, label="User Prompt (Optional, Enter with commas)")
          
            with gr.Row():
                with gr.Column(sclae=0.3, min_width=0):
                    caption = gr.Button("✍ Upload")
                    chat_video = gr.Button(" 🎥 Let's Chat! ", interactive=False)
                with gr.Column(scale=0.7, min_width=0):
                    loadinglabel = gr.Label(label="State")
        with gr.Column():
            openai_api_key_textbox = gr.Textbox(
                value=os.environ["OPENAI_API_KEY"],
                placeholder="Paste your OpenAI API key here to start (sk-...)",
                show_label=False,
                lines=1,
                type="password",
            )
            chatbot = gr.Chatbot(elem_id="chatbot", label="gpt")
            state = gr.State([])
            user_tag_output = gr.State("")
            image_caption_output = gr.State("")
            video_caption_output  = gr.State("")
            model_tag_output = gr.State("")
            dense_caption_output = gr.State("")
            with gr.Row(visible=False) as input_raws:
                with gr.Column(scale=0.8):
                    txt = gr.Textbox(show_label=False, placeholder="Enter text and press enter").style(container=False)
                with gr.Column(scale=0.10, min_width=0):
                    run = gr.Button("🏃‍♂️Run")
                with gr.Column(scale=0.10, min_width=0):
                    clear = gr.Button("🔄Clear️")    

    
    caption.click(bot.memory.clear)
    caption.click(lambda: gr.update(interactive = False), None, chat_video)
    caption.click(lambda: [], None, chatbot)
    caption.click(lambda: [], None, state)    
    caption.click(inference,[input_video_path,input_tag],[model_tag_output, user_tag_output, image_caption_output, dense_caption_output,video_caption_output, chat_video, loadinglabel])

    chat_video.click(bot.init_agent, [openai_api_key_textbox, image_caption_output, dense_caption_output, video_caption_output, model_tag_output, state], [input_raws,chatbot, state])

    txt.submit(bot.run_text, [txt, state], [chatbot, state])
    txt.submit(lambda: "", None, txt)
    run.click(bot.run_text, [txt, state], [chatbot, state])
    run.click(lambda: "", None, txt)

    clear.click(bot.memory.clear)
    clear.click(lambda: [], None, chatbot)
    clear.click(lambda: [], None, state)
    


demo.launch(server_name="0.0.0.0",enable_queue=True,)#share=True)
