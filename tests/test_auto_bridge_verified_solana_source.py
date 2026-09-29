"""No-network safety checks for cross-chain source balance discovery.

A bridge must use spendable canonical Solana USDC, not an indexed display
balance that can return HTTP 429 or include unusable non-ATA accounts.
No wallet signature, bridge, quote or transaction is invoked by this test.
"""
import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'dashboard.py').read_text()
fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)
        and n.name=='_find_bridge_source_chain')


def picker(*, sol_balance=0., evm_balances=None, rpc_error=False, wallet_override='TradingWallet'):
    called=[]
    evm_balances=evm_balances or {}
    def read(wallet):
        called.append(('solana_direct',wallet))
        if rpc_error:raise RuntimeError('Solana bot balances unavailable from verified RPC')
        return 0.002, sol_balance
    def evm(address,chain):
        called.append(('evm',address,chain))
        return evm_balances.get(chain,0.)
    def indexed(wallet):
        raise AssertionError('The auto-bridge must not call indexed RPC balance reader')
    ns={'_AUTO_BRIDGE_BUFFER_PCT':0.05,
        '_get_trading_wallet_address':lambda user:wallet_override,
        '_get_bot_solana_balances':read,
        '_get_solana_usdc_balance':indexed,
        'USDC_MINT':'SolanaCanonicalUSDC',
        'EVM_CHAINS':{'base':{'usdc':'BaseUSDC'},
                      'bsc':{'usdc':'BscUSDC'},
                      'arbitrum':{'usdc':'ArbitrumUSDC'}},
        'get_evm_usdc_balance':evm}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(ROOT/'dashboard.py'),'exec'),ns)
    return ns['_find_bridge_source_chain'],called


def test_bridge_only_selects_spendable_ata_with_buffer():
    pick,calls=picker(sol_balance=10.6,evm_balances={'bsc':9.,'arbitrum':9.})
    assert pick('WebAppUser','EvmWallet','base',10.)==('solana','SolanaCanonicalUSDC',10.6)
    assert calls[0]==('solana_direct','TradingWallet')
    assert ('evm','EvmWallet','base') not in calls
    pick,_=picker(sol_balance=10.49)
    assert pick('WebAppUser','','base',10.) is None
    print('PASS spendable ATA must cover 105% source budget; real trading wallet selected')


def test_bridge_source_chooses_highest_qualifying_and_skips_destination():
    pick,calls=picker(sol_balance=10.6,evm_balances={'bsc':11.4,'arbitrum':11.0,'base':90.})
    assert pick('WebAppUser','EvmWallet','base',10.)==('bsc','BscUSDC',11.4)
    assert ('evm','EvmWallet','base') not in calls
    print('PASS existing EVM source choices and destination exclusion stay intact')


def test_rpc_unknown_fails_closed_without_blocking_verified_evm_source():
    pick,calls=picker(rpc_error=True,evm_balances={'bsc':12.})
    assert pick('WebAppUser','EvmWallet','base',10.)==('bsc','BscUSDC',12.)
    pick,calls=picker(rpc_error=True)
    assert pick('WebAppUser','','base',10.) is None
    print('PASS missing Solana RPC data cannot authorize a bridge; verified EVM remains eligible')


def test_other_wallet_or_unspendable_display_balance_never_selected():
    pick,calls=picker(sol_balance=0.,wallet_override='TradingWallet',
                      evm_balances={'bsc':1.})
    assert pick('WebAppUser','EvmWallet','base',10.) is None
    assert calls[0]==('solana_direct','TradingWallet')
    assert '_get_solana_usdc_balance(solana_wallet)' not in ast.get_source_segment(source,fn)
    print('PASS no false USDC source from another wallet/non-ATA display balance')

if __name__=='__main__':
    test_bridge_only_selects_spendable_ata_with_buffer()
    test_bridge_source_chooses_highest_qualifying_and_skips_destination()
    test_rpc_unknown_fails_closed_without_blocking_verified_evm_source()
    test_other_wallet_or_unspendable_display_balance_never_selected()
