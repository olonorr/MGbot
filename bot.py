import telebot
import requests
from telebot import apihelper

# tg://proxy?server=127.0.0.1&port=1443&secret=dd937831d99b1c474e73fc755198464909

apihelper.proxy = {'https': 'http://127.0.0.1:1443'}



bot = telebot.TeleBot(TOKEN)


@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id, 'Hello')


bot.polling(non_stop=True)