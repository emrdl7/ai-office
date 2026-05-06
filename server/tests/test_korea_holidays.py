import httpx


def test_public_holiday_json_lookup(monkeypatch):
    from integrations import korea_holidays

    korea_holidays._CACHE.clear()
    monkeypatch.setenv('KOREA_HOLIDAY_API_KEY', 'test-key')
    request = httpx.Request('GET', 'https://example.test')

    def fake_get(url, params, timeout):
        assert params['solYear'] == '2026'
        assert params['solMonth'] == '05'
        return httpx.Response(
            200,
            request=request,
            headers={'content-type': 'application/json'},
            json={
                'response': {
                    'body': {
                        'items': {
                            'item': [
                                {'dateName': '어린이날', 'locdate': 20260505, 'isHoliday': 'Y', 'dateKind': '01'},
                                {'dateName': '잡절', 'locdate': 20260506, 'isHoliday': 'N', 'dateKind': '04'},
                            ],
                        },
                    },
                },
            },
        )

    monkeypatch.setattr(korea_holidays.httpx, 'get', fake_get)

    assert korea_holidays.get_public_holidays('2026-05') == [
        {'date': '2026-05-05', 'name': '어린이날', 'kind': '01', 'sequence': ''},
    ]


def test_public_holiday_xml_lookup(monkeypatch):
    from integrations import korea_holidays

    korea_holidays._CACHE.clear()
    monkeypatch.setenv('KOREA_HOLIDAY_API_KEY', 'test-key')
    request = httpx.Request('GET', 'https://example.test')

    def fake_get(url, params, timeout):
        return httpx.Response(
            200,
            request=request,
            headers={'content-type': 'application/xml'},
            text='''<response><body><items><item>
                <dateName>부처님오신날</dateName><locdate>20260524</locdate><isHoliday>Y</isHoliday><dateKind>01</dateKind><seq>1</seq>
            </item></items></body></response>''',
        )

    monkeypatch.setattr(korea_holidays.httpx, 'get', fake_get)

    assert korea_holidays.get_public_holidays('2026-05') == [
        {'date': '2026-05-24', 'name': '부처님오신날', 'kind': '01', 'sequence': '1'},
    ]


def test_public_holiday_missing_key_falls_back(monkeypatch):
    from integrations import korea_holidays

    korea_holidays._CACHE.clear()
    monkeypatch.delenv('KOREA_HOLIDAY_API_KEY', raising=False)
    monkeypatch.delenv('PUBLIC_DATA_SERVICE_KEY', raising=False)
    monkeypatch.delenv('DATA_GO_KR_SERVICE_KEY', raising=False)

    assert korea_holidays.get_public_holidays('2026-05') == []
