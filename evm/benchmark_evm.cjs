const fs = require('fs');
const solc = require('solc');
const ganache = require('ganache');
const { ethers } = require('ethers');

async function main(){
  const [solFile, calldataFile, outFile] = process.argv.slice(2);
  const source=fs.readFileSync(solFile,'utf8');
  const input={language:'Solidity',sources:{'Verifier.sol':{content:source}},settings:{optimizer:{enabled:true,runs:200},outputSelection:{'*':{'*':['abi','evm.bytecode.object']}}}};
  const output=JSON.parse(solc.compile(JSON.stringify(input)));
  if(output.errors){ const fatal=output.errors.filter(e=>e.severity==='error'); if(fatal.length) throw new Error(fatal.map(x=>x.formattedMessage).join('\n')); }
  const contracts=output.contracts['Verifier.sol'];
  const name=Object.keys(contracts).find(n=>contracts[n].evm.bytecode.object.length>0);
  const c=contracts[name];
  const provider = new ethers.BrowserProvider(ganache.provider({logging:{quiet:true},wallet:{totalAccounts:2},chain:{chainId:31337}}));
  const signer=await provider.getSigner();
  const factory=new ethers.ContractFactory(c.abi,'0x'+c.evm.bytecode.object,signer);
  const deploy=await factory.deploy();
  const depReceipt=await deploy.deploymentTransaction().wait();
  await deploy.waitForDeployment();
  const raw=fs.readFileSync(calldataFile,'utf8').trim();
  const args=eval('['+raw+']'); // generated locally by snarkjs, not user-controlled input
  const fn=deploy.interface.getFunction('verifyProof');
  const valid=await deploy.verifyProof(...args);
  if(!valid) throw new Error('Solidity verifier rejected the valid proof');
  const gasEstimate=await deploy.verifyProof.estimateGas(...args);
  const data=deploy.interface.encodeFunctionData(fn,args);
  const tx=await signer.sendTransaction({to:await deploy.getAddress(),data,gasLimit:gasEstimate*2n});
  const receipt=await tx.wait();
  const row={contract:name,deployment_gas:depReceipt.gasUsed.toString(),verify_estimate_gas:gasEstimate.toString(),verify_tx_gas:receipt.gasUsed.toString(),proof_valid:valid,chain_id:31337};
  fs.writeFileSync(outFile,'metric,value\n'+Object.entries(row).map(([k,v])=>`${k},${v}`).join('\n')+'\n');
  console.log(row);
}
main().catch(e=>{console.error(e);process.exit(1)});
