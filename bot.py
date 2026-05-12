import telebot
#import websockets
import json
import asyncio

bot = telebot.TeleBot("8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4")
uri = "wss://magicgarden.gg/version/311/api/rooms/7TWG/connect?surface=%22web%22&platform=%22desktop%22&playerId=%22p_KWTb7ix7rFYy9yhS%22&version=%22311%22&anonymousUserStyle=%7B%22color%22%3A%22White%22%2C%22avatarBottom%22%3A%22Bottom_DefaultGray.png%22%2C%22avatarMid%22%3A%22Mid_DefaultGray.png%22%2C%22avatarTop%22%3A%22Top_DefaultGray.png%22%2C%22avatarExpression%22%3A%22Expression_Default.png%22%2C%22name%22%3A%22Sunny+Apple%22%7D&source=%22manualUrl%22&capabilities=%22fbo_mipmap_unsupported%22"
'''
async def listen():
    async with websockets.connect(uri) as websocket:
        while True:
            data = await websocket.recv()
            try:
                json_data = json.loads(data)
                if 'type' in json_data:
                    if json_data['type'] == 'Welcome':
                        json_data = json_data['fullState']['child']['data']['shops']
                        json_data['seed']['inventory']
                        fdata = ""
                        for i in json_data['seed']['inventory']:
                            f = "{0} - {1}\n".format(i['species'], i['initialStock'])
                            fdata += f
                        return(fdata)
            except json.JSONDecodeError as e:
                print(f"Ошибка парсинга JSON: {e}")
                print(f"Полученные данные: {data}")
            

def getData() -> str:
    return (asyncio.run(listen()))
'''

@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id, "getData()")


bot.polling(non_stop=True)