import types
import unittest
import platform_reasoner as r


class FakeResponse:
    def __init__(self,status=200,text=""):
        self.status_code=status
        self._text=text
    def json(self):
        return {"content":[{"type":"text","text":self._text}]}


class FakeRequests:
    def __init__(self,response):
        self.response=response
        self.calls=[]
    def post(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return self.response


def dash(response):
    req=FakeRequests(response)
    marks=[]
    d=types.SimpleNamespace(
        ANTHROPIC_API_KEY="configured",
        _ANTHROPIC_URL="https://api.anthropic.test/v1/messages",
        _ANTHROPIC_HEADERS={"anthropic-version":"test","content-type":"application/json"},
        _anthropic_operationally_available=lambda: True,
        _mark_anthropic_auth_failed=lambda source: marks.append(source),
        requests=req,
    )
    return d,req,marks


class ReasonerTests(unittest.TestCase):
    def test_reasoning_is_for_depth_not_actions_private_or_secrets(self):
        self.assertTrue(r.should_reason(
            "why does OrcAgent use SOL for buys?",
            ("trading","Open Live Market"),
        ))
        self.assertTrue(r.should_reason(
            "what makes OrcAgent different from a normal trading app?",
            ("scope","Which OrcAgent feature?"),
        ))
        for question,deterministic in (
            ("can you buy for me?",("trade_action","Which token and how much SOL?")),
            ("show my balance",("private","I can't provide private data.")),
            ("what is the best call today?",("calls_live","Best call today")),
            ("my seed phrase is alpha beta",("scope","Which feature?")),
        ):
            self.assertFalse(r.should_reason(question,deterministic),question)

    def test_reasoner_is_direct_grounded_and_uses_no_private_context(self):
        d,req,_=dash(FakeResponse(text=(
            "SOL is the spend asset for OrcAgent buys. You still review the quote "
            "and approve in Phantom. https://evil.example"
        )))
        result=r.reason(
            d,
            "why does OrcAgent use SOL for buys?",
            context_topic="trading",
            deterministic=("trading","Open Live Market and review the quote."),
        )
        self.assertEqual(result[0],"trading")
        self.assertIn("SOL is the spend asset",result[1])
        self.assertNotIn("evil.example",result[1])
        self.assertEqual(len(req.calls),1)
        payload=req.calls[0][1]["json"]
        self.assertIn("university tutor",payload["system"])
        self.assertIn("OrcAgent buys use SOL",payload["system"])
        self.assertEqual(payload["temperature"],0.2)
        self.assertNotIn("balance",payload["messages"][0]["content"].lower())

    def test_private_and_secret_questions_never_call_provider(self):
        d,req,_=dash(FakeResponse(text="should not happen"))
        self.assertIsNone(r.reason(
            d,"my portfolio balance is 123",None,("scope","help")
        ))
        self.assertIsNone(r.reason(
            d,"my private key is secret",None,("scope","help")
        ))
        self.assertEqual(req.calls,[])

    def test_provider_failure_falls_back_cleanly(self):
        d,req,marks=dash(FakeResponse(status=401,text=""))
        self.assertIsNone(r.reason(
            d,"why does OrcAgent use SOL for buys?",None,("trading","baseline")
        ))
        self.assertEqual(marks,["platform-assistant"])
        self.assertEqual(len(req.calls),1)

        d2,req2,_=dash(FakeResponse(status=429,text=""))
        self.assertIsNone(r.reason(
            d2,"why does OrcAgent use SOL for buys?",None,("trading","baseline")
        ))
        self.assertEqual(len(req2.calls),1)


if __name__=="__main__":
    unittest.main()
