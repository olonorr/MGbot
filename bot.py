import telebot

bot = telebot.TeleBot(8538742738:AAF2QqkbRkMueE1fOg-n7Yb1EFRRnXOjPV4)


@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id, 'Hello')


bot.polling(non_stop=True)