import os
import asyncio
from urllib.parse import urlparse, urlunparse, urljoin
import time
import pdfplumber
from playwright.async_api import Page
from playwright._impl._errors import TargetClosedError
from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
from dotenv import load_dotenv
from ..utils.scrap_utils.req_backend import save_bills
from ..utils.scrap_utils.get_selector import get_selector

load_dotenv()


class ScrapService:
    def __init__(self, browser):
        self.browser = browser
        self.solver = recaptchaV2Proxyless()
        self.solver.set_verbose(1)
        self.solver.set_key(os.getenv("KEY_ANTICAPTCHA"))
        self.global_bills = []
        self.save_bills_called = False
        self.debt = False

    async def search(self, data):
        url = data["service"]["scrapping_config"]["url"]
        captcha = data["service"]["scrapping_config"]["captcha"]
        page = await self.browser.navigate_to_page(url)

        try:
            result = await self.parser(data, page, captcha)
        except Exception as e:
            print(f"Error: {e}")
            await page.close()
            return await self.search(data)

        await page.close()
        return self.debt, result

    async def parser(self, data, page: Page, captcha):
        sequence = data["service"]["scrapping_config"]["sequence"]
        client_number = data["provider_client"]["client_code"]
        client_number_index = 0
        provider_client_id = data["provider_client"]["id"]

        if captcha:
            page.on("dialog", self.handle_dialog)
            page.on("download", self.handle_download)
            captcha_sequence = data["service"]["scrapping_config"]["captcha_sequence"]
            try:
                await self.handle_captcha(data, page, captcha_sequence, client_number)
            except TimeoutError:
                print("TimeoutError SCRAP. Reattempting...")
                await page.close()
                return await self.search(data)

        consecutive_errors = 0

        for action in sequence:
            try:
                client_number_index = await self.execute_action(
                    page, action, client_number, provider_client_id, client_number_index
                )
                consecutive_errors = 0
            except Exception as e:
                print(f"Error executing action: {e}")
                consecutive_errors += 1
                if consecutive_errors == 2:
                    print("Two consecutive elements not found. Restarting...")
                    await page.close()
                    return await self.search(data)
                else:
                    print("Element not found, skipping to next action")
                    continue

        if captcha and not self.save_bills_called:
            await save_bills(provider_client_id, self.global_bills)

        return True

    async def handle_captcha(self, data, page, captcha_sequence, client_number):
        await page.fill(get_selector(captcha_sequence[0]), str(client_number))
        sitekey_element = await page.query_selector(captcha_sequence[1]["content"])
        sitekey_clean = await sitekey_element.get_attribute("data-sitekey")
        await self.solve_captcha(
            data, page, sitekey_clean, captcha_sequence[2]["captcha_button_content"]
        )

    async def execute_action(
        self, page, action, client_number, provider_client_id, client_number_index
    ):
        element_type = action["element_type"]
        selector = get_selector(action)
        debt = action.get("debt", False)
        no_debt_text = action.get("no_debt_text", None)

        await page.wait_for_selector(selector, timeout=5000)

        if element_type in ["input", "button"]:
            client_number_index = await self.handle_input_or_button(
                page, action, selector, client_number, client_number_index
            )
        elif element_type in [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "div",
            "span",
            "table",
            "tbody",
            "td",
            "a",
            "ul",
        ]:
            await self.handle_element(
                page, action, debt, no_debt_text, provider_client_id
            )
        elif element_type == "modal":
            await self.handle_modal(page, selector)
        elif element_type == "buttons":
            await self.handle_buttons(page, selector)

        return client_number_index

    async def handle_input_or_button(
        self, page, action, selector, client_number, client_number_index
    ):
        if action["element_type"] == "input":
            size = int(action.get("size", len(client_number)))
            input_value = client_number[
                client_number_index : client_number_index + size
            ]
            await page.fill(selector, input_value)
            client_number_index += size
        elif action["element_type"] == "button":
            await page.click(selector)
        return client_number_index

    async def handle_element(
        self, page, action, debt, no_debt_text, provider_client_id
    ):
        elements = await page.query_selector_all(get_selector(action))
        if elements and debt:
            debt_message = await elements[0].inner_text()
            self.debt = no_debt_text not in debt_message if no_debt_text else True

        if action.get("query"):
            await self.handle_query(page, action, elements, provider_client_id)

    async def handle_query(self, page, action, elements, provider_client_id):
        if action.get("redirect"):
            href = await elements[0].get_attribute("href")
            absolute_url = urljoin(page.url, href)
            await page.goto(absolute_url, wait_until="load")
        elif action.get("form"):
            for i in range(0, 6, 2):
                td = elements[i]
                form = await td.query_selector("form")
                await form.dispatch_event("submit")
                await asyncio.sleep(12)
        else:
            elements_href = [
                await element.get_attribute("href") for element in elements
            ]
            base_url = urlunparse(urlparse(page.url)._replace(path=""))
            elements_formatted = [
                {"url": urljoin(base_url, href)}
                for href in elements_href
                if href is not None
            ]
            await save_bills(provider_client_id, elements_formatted)
            self.save_bills_called = True

    async def handle_modal(self, page, selector):
        await page.wait_for_selector(selector)
        try:
            await page.click(selector)
        except Exception:
            print("Modal not found")

    async def handle_buttons(self, page, selector):
        buttons = await page.query_selector_all(selector)
        for button in buttons:
            await button.click()

    async def solve_captcha(self, data, page, sitekey_clean, captcha_button_content):
        try:
            self.solver.set_website_url(page.url)
            self.solver.set_website_key(sitekey_clean)
            g_response = self.solver.solve_and_return_solution()
            if g_response != 0:
                await page.evaluate(
                    f"document.getElementById('g-recaptcha-response').innerHTML = '{g_response}'"
                )
                await page.click(captcha_button_content)
            else:
                print("Task finished with error " + self.solver.error_code)
        except Exception:
            print("TimeoutError SOLVE CAPTCHA. Reattempting...")
            await page.close()
            return await self.search(data)

    async def handle_dialog(self, dialog):
        print(f"Dialog message: {dialog.message}")
        await dialog.accept()

    async def handle_download(self, download):
        time.sleep(2)
        print(f"Descargando: {download.suggested_filename}")
        try:
            path = await download.path()
        except TargetClosedError:
            print(
                "La página, el contexto o el navegador se han cerrado antes de que se pudiera acceder a la ruta del archivo descargado."
            )
            return
        print(f"Guardado en: {path}")

        with pdfplumber.open(path) as pdf:
            pages = pdf.pages
            text = "".join(page.extract_text() for page in pages)
        self.global_bills.append({"content": text})
        time.sleep(2)
