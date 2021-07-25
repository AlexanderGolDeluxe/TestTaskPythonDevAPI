import datetime, hashlib, requests
from flask import Flask, json, render_template, redirect, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///payform.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# секретный ключ магазина (из настроек магазина)
secret = "SecretKey01"
# email плательщика на стороне платежной системы Piastrix
payer_account = "support@piastrix.com"
# обязательный параметр для метода Invoice
payway_for_invoice = "advcash_rub"
# валюта выставленного счёта
currency_code = {
  "EUR": "978",
  "USD": "840",
  "RUB": "643",
  "UAH": "980"
}
# ссылки для создания запроса на выставление счёта на оплату
payway_url = {
  "EUR": "https://pay.piastrix.com/ru/pay",
  "USD": "https://core.piastrix.com/bill/create",
  "RUB": "https://core.piastrix.com/invoice/create"
}


class PayServiceLog(db.Model):
  """Логирование работы сервиса и хранение следующей информации:\n
     id – идентификатор платежа в БД;
     shop_id – идентификатор магазина в системе Piastrix;
     shop_order_id – номер счёта на стороне магазина;
     amount – сумма выставленного счёта;
     currency – валюта выставленного счёта;
     description – описание к выставленному счёту;
     created – время отправки.
  """
  id = db.Column(db.Integer, primary_key=True)
  shop_id = db.Column(db.Integer)
  shop_order_id = db.Column(db.String(255))
  amount = db.Column(db.Float, nullable=False)
  currency = db.Column(db.String, nullable=False)
  description = db.Column(db.Text, nullable=True)
  created = db.Column(db.DateTime, default=datetime.datetime.now())


def sign_create(params: dict, not_required_params: tuple):
  """Строка 'sign' формируется следующим образом:\n
     все обязательные параметры запроса упорядочиваются в алфавитном порядке ключей,
     значения конкатенируются через знак двоеточие (“:”), в конце добавляется секретный ключ (без знака ":"),
     от полученной строки генерируется sha256 хеш и его HEX-представление возвращается в параметр запроса 'sign'.
  """
  keys_sorted = ":".join(params[keys] for keys in sorted(params.keys()) if not keys in not_required_params) + secret
  return hashlib.sha256(keys_sorted.encode()).hexdigest()


def response_json_create(params_names: list, params_values: list, not_required_params: tuple, currency: str, content_type: dict):
  """Данной функцией осуществляется запрос на выставление счёта на оплату по API
  """
  payway_data = dict(zip(params_names, params_values))
  payway_data.update({"sign": sign_create(payway_data, not_required_params)})
  resp = requests.post(payway_url[currency], json.dumps(payway_data), headers=content_type)
  resp = json.loads(resp.text)
  return resp


@app.route("/", methods=["GET", "POST"])
def index():
  """Сервис состоит из одной страницы со следующими элементами:\n
     Сумма оплаты (поле ввода суммы);
     Валюта оплаты (выпадающий список со значениями EUR, USD, RUB);
     Описание товара (многострочное поле ввода информации);
     Оплатить (кнопка);
  """
  index_data = {
    "shop_id": 5,
    "shop_order_id": "101"
  }
  if request.method == "POST":
    pay_log = PayServiceLog(
      shop_id = index_data["shop_id"],
      shop_order_id = index_data["shop_order_id"],
      amount = request.form["amount"],
      currency = request.form["currency"],
      description = request.form["description"]
    )

    try:
      db.session.add(pay_log)
      db.session.commit()
    except:
      return "<h2>[UNKNOWN ERROR] – Something is wrong.<br>Please return to form and enter a valid data.</h2>"
    else:
      h = {'Content-Type' : 'application/json'}
      # список параметров для запроса
      standart_params_names = ["amount", "currency", "shop_id", "shop_order_id", "description"]
      # список значений соответствующий параметрам из списка для запроса
      standart_params_values = ["%0.2f" % pay_log.amount, currency_code[pay_log.currency], str(pay_log.shop_id), pay_log.shop_order_id, pay_log.description]
      # Выставление счёта для оплаты в валюте Piastix методом Bill
      if pay_log.currency == "USD":
        bill_params_names = ["shop_amount", "shop_currency", "shop_id", "shop_order_id", "description", "payer_currency", "payer_account"]
        bill_resp = response_json_create(bill_params_names, standart_params_values + [currency_code[pay_log.currency], payer_account], ("description", "payer_account"), pay_log.currency, h)
        try:
          return redirect(bill_resp["data"]["url"])
        except:
          return f"<h2>[ERROR {bill_resp['error_code']}] – {bill_resp['message']}<br>Please return to form and enter a valid data.</h2>"
      # Выставление счёта для других валют методом Invoice
      elif pay_log.currency == "RUB":
        invoice_resp = response_json_create(standart_params_names + ["payway"], standart_params_values + [payway_for_invoice], ("description"), pay_log.currency, h)
        try:
          invoice_data = {
            "payway_data": invoice_resp["data"]["data"],
            "method": invoice_resp["data"]["method"],
            "url": invoice_resp["data"]["url"]
          }
          return render_template("pay.html", data=invoice_data)
        except:
          return f"<h2>[ERROR {invoice_resp['error_code']}] – {invoice_resp['message']}<br>Please return to form and enter a valid data.</h2>"
      elif pay_log.amount < 0.01:
        return "<h2>[ERROR 4] – Payer amount is too small, min: 0.01<br>Please return to form and enter a valid data.</h2>"
      elif pay_log.amount > 9999999999999998:
        return "<h2>[ERROR 5] – Payer amount is too large, max: 9 999 999 999 999 998<br>Please return to form and enter a valid data.</h2>"
      # Выставление счёта для оплаты через PAY
      else:
        pay_data = {
          "payway_data": dict(zip(standart_params_names, standart_params_values)),
          "method": "POST",
          "url": payway_url[pay_log.currency]
        }
        pay_data["payway_data"].update({"sign": sign_create(pay_data["payway_data"], ("description"))})
        return render_template("pay.html", data=pay_data)
  else:
    return render_template("index.html", data=index_data)


if __name__ == "__main__":
  app.run(debug=True)