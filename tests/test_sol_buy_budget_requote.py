"""No funds or network: exercise guard + adaptive sizing with mocked routes."""
from unittest.mock import patch
import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.transaction import Transaction
import orcagent_solana as engine

@pytest.fixture(autouse=True)
def isolate_budget_globals():
    with patch.object(engine,'_BUY_MAX_OUTFLOW_LAMPORTS',0),patch.object(engine,'_BUY_ESTIMATED_OUTFLOW_LAMPORTS',0):
        yield

@pytest.mark.parametrize('route_cost',[500_000,4_200_000,6_000_000])
def test_screenshot_budget_resizes_before_a_single_send_and_preserves_fee(route_cost):
    budget=14_435_150
    calls=[];sent=[]
    payer=Keypair();tx=Transaction([payer],Message.new_with_blockhash([],payer.pubkey(),Hash.default()),Hash.default())
    spend=0
    def rpc(body,**kw):
        method=body['method']
        value={'getBalance':1_000_000_000,'getFeeForMessage':5_000,
               'simulateTransaction':{'err':None,'accounts':[{'lamports':1_000_000_000-spend-route_cost}]}}[method]
        return {'result':{'value':value}}
    def execute(input_mint,mint,amount,**kw):
        nonlocal spend
        spend=amount;calls.append((input_mint,amount,kw))
        engine._assert_native_budget('mock-signed',tx)
        sent.append(amount+route_cost)
        return 'signature','1000'
    with patch.object(engine,'_native_buy_cost_allowance',return_value=3_000_000),patch.object(engine,'_rpc_post',side_effect=rpc),patch.object(engine,'execute_swap',side_effect=execute):
        sig,out,last=engine._execute_native_budget_buy('token',budget,'fee-wallet',100)
    assert (sig,out)==('signature','1000')
    assert len(sent)==1 and sent[0]<=budget
    assert all(c[0]==engine.SOL_MINT and c[2]=={'fee_wallet':'fee-wallet','fee_bps':100} for c in calls)
    assert last==calls[-1][1]
    assert len(calls)==(1 if route_cost<3_000_000 else 2)
    assert engine._BUY_MAX_OUTFLOW_LAMPORTS==budget
    assert engine._BUY_ESTIMATED_OUTFLOW_LAMPORTS<=budget

@pytest.mark.parametrize('error',[RuntimeError('Cannot verify the SOL spend ceiling; transaction not sent'),
                                  RuntimeError('RPC broadcast timed out'),RuntimeError('Confirmation timeout')])
def test_unknown_preflight_or_post_send_errors_are_never_retried(error):
    with patch.object(engine,'_native_buy_cost_allowance',return_value=3_000_000),patch.object(engine,'execute_swap',side_effect=error) as execute:
        with pytest.raises(RuntimeError,match=str(error)):
            engine._execute_native_budget_buy('token',14_435_150,'fee-wallet',100)
        assert execute.call_count==1

def test_changing_route_costs_stop_after_three_unsent_checks():
    budget=14_435_150
    error=engine.NativeBuyBudgetExceeded(budget+200_000,budget)
    with patch.object(engine,'_native_buy_cost_allowance',return_value=3_000_000),patch.object(engine,'execute_swap',side_effect=error) as execute:
        with pytest.raises(engine.NativeBuyBudgetExceeded):
            engine._execute_native_budget_buy('token',budget,'fee-wallet',100)
        assert execute.call_count==3

def test_budget_too_small_for_initial_or_measured_rent_is_rejected_before_send():
    for budget in [2_000_000,4_000_000]:
        with patch.object(engine,'_native_buy_cost_allowance',return_value=3_000_000),patch.object(engine,'execute_swap',side_effect=engine.NativeBuyBudgetExceeded(budget+3_000_000,budget)) as execute:
            with pytest.raises(ValueError,match='transaction not sent'):
                engine._execute_native_budget_buy('token',budget,'fee-wallet',100)
            assert execute.call_count==(0 if budget==2_000_000 else 1)

def test_invalid_guard_measurement_cannot_reduce_or_broadcast_again():
    budget=14_435_150
    for error in [engine.NativeBuyBudgetExceeded(budget,budget),engine.NativeBuyBudgetExceeded(budget+100_000,budget-1)]:
        with patch.object(engine,'_native_buy_cost_allowance',return_value=3_000_000),patch.object(engine,'execute_swap',side_effect=error) as execute:
            with pytest.raises(engine.NativeBuyBudgetExceeded):
                engine._execute_native_budget_buy('token',budget,'fee-wallet',100)
            assert execute.call_count==1
